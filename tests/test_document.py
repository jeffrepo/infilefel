"""Isolated Odoo method tests; does not substitute for installing on Odoo 17."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock
from contextlib import nullcontext
from datetime import datetime, timezone, timedelta

from test_transport import UUID, response

ROOT = Path(__file__).resolve().parents[1]


class UserError(Exception):
    pass


class FieldFacade:
    Datetime = types.SimpleNamespace(
        now=lambda: datetime(2026, 10, 13, 18, 0, 0),
        context_timestamp=lambda rec, dt: dt.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-6))))

    def __getattr__(self, name):
        return lambda *args, **kwargs: False


def load_models():
    odoo = types.ModuleType('odoo')
    odoo.fields = FieldFacade()
    odoo.models = types.SimpleNamespace(AbstractModel=object, Model=object, TransientModel=object)
    odoo._ = lambda value: value
    exceptions = types.ModuleType('odoo.exceptions')
    exceptions.UserError = UserError
    previous = {name: sys.modules.get(name) for name in ('odoo', 'odoo.exceptions')}
    sys.modules.update({'odoo': odoo, 'odoo.exceptions': exceptions})
    package = types.ModuleType('vitec_test_models')
    package.__path__ = [str(ROOT / 'models')]
    sys.modules[package.__name__] = package
    modules = {}
    try:
        for name in ('infile_transport', 'vitec_xml', 'document_vitec', 'account_move_vitec', 'account_payment_vitec'):
            spec = importlib.util.spec_from_file_location('vitec_test_models.' + name, ROOT / 'models' / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            modules[name] = module
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return modules


MODULES = load_models()
Document = MODULES['document_vitec'].InfileVitecDocument
transport = MODULES['infile_transport']
Move = MODULES['account_move_vitec'].AccountMove
Payment = MODULES['account_payment_vitec'].AccountPayment


class FakeDocument(Document):
    _name = 'account.move'
    id = 16661
    l10n_xma_einvoice_status = False
    l10n_xma_einvoice_numero = False
    l10n_xma_cancel_motive = 'Error de emisión'

    def __init__(self, post):
        self.company_id = types.SimpleNamespace(id=2)
        self.env = types.SimpleNamespace(cr=Mock())
        self.env.cr.savepoint.side_effect = lambda: nullcontext()
        self.post = post
        self.message_post = Mock()
        self.saved = []
        self.ensure_one = Mock()

    def _infile_lock(self):
        pass

    def _infile_client(self):
        return transport.InfileClient(user='TEST', api_key='TEST-API-KEY', signer_key='TEST-SIGNER-KEY',
                                     nit='12345K', email='', post=self.post)

    def write(self, values):
        self.saved.append(dict(values))
        for key, value in values.items():
            setattr(self, key, value)


def prepare():
    return b'<XML/>', {'emission': '2026-10-13T12:00:00-06:00', 'issuer': '12345K',
                       'receiver': 'CF', 'phrases': {'dte:Frase': [{'@TipoFrase': '1', '@CodigoEscenario': 2}]}}


class DocumentTests(unittest.TestCase):
    def test_success_uses_confirmed_vitec_field_mapping_and_commits_before_http(self):
        def server(url, **kwargs):
            self.assertEqual(doc.infile_vitec_state, 'pending')
            self.assertGreaterEqual(doc.env.cr.commit.call_count, 1)
            if url == transport.SIGN_URL:
                return response({'resultado': True, 'archivo': 'SIGNED'})
            return response({'resultado': True, 'uuid': UUID, 'serie': '9233BF7F', 'numero': 3204071584})
        doc = FakeDocument(Mock(side_effect=server))
        action = doc._infile_run(prepare)
        self.assertEqual(doc.l10n_xma_uuid_invoice, '9233BF7F')
        self.assertEqual(doc.l10n_xma_einvoice_serie, '3204071584')
        self.assertEqual(doc.l10n_xma_einvoice_numero, UUID)
        self.assertEqual(doc.l10n_xma_einvoice_status, 'signed')
        self.assertEqual(action['params']['type'], 'success')
        diagnostic = json.loads(doc.infile_vitec_diagnostic)
        self.assertEqual(diagnostic['company_id'], 2)
        self.assertEqual(diagnostic['phrases'], prepare()[1]['phrases'])
        self.assertFalse(diagnostic['adenda_present'])
        with self.assertRaises(UserError):
            doc._infile_run(prepare)
        self.assertEqual(doc.post.call_count, 2)

    def test_timeout_blocks_retry_and_keeps_diagnostic(self):
        import requests
        doc = FakeDocument(Mock(side_effect=[response({'resultado': True, 'archivo': 'SIGNED'}), requests.ReadTimeout()]))
        action = doc._infile_run(prepare)
        self.assertEqual(doc.infile_vitec_state, 'uncertain')
        self.assertIn('INFILE_TRANSPORT_ERROR', doc.infile_vitec_diagnostic)
        self.assertEqual(action['params']['type'], 'warning')
        with self.assertRaises(UserError):
            doc._infile_run(prepare)
        self.assertEqual(doc.post.call_count, 2)

    def test_crash_after_committed_intent_stays_pending(self):
        doc = FakeDocument(Mock(side_effect=RuntimeError('process interrupted')))
        with self.assertRaises(RuntimeError):
            doc._infile_run(prepare)
        self.assertEqual(doc.infile_vitec_state, 'pending')
        with self.assertRaises(UserError):
            doc._infile_run(prepare)
        self.assertEqual(doc.post.call_count, 1)

    def test_rejection_is_visible_and_permits_corrected_attempt(self):
        doc = FakeDocument(Mock(return_value=response({'resultado': False, 'codigo': 5, 'descripcion': '<b>rechazo</b>'})))
        doc._infile_run(prepare)
        identifier = doc.infile_vitec_identifier
        self.assertEqual(doc.infile_vitec_state, 'failed')
        self.assertEqual(doc.l10n_xma_einvoice_status, 'failed')
        self.assertIn('&lt;b&gt;', str(doc.message_post.call_args.kwargs['body']))
        doc._infile_run(prepare)
        self.assertNotEqual(doc.infile_vitec_identifier, identifier)

    def test_failed_cancellation_keeps_signed_status_and_uuid(self):
        doc = FakeDocument(Mock(return_value=response({'resultado': False, 'codigo': 5})))
        doc.l10n_xma_einvoice_status = 'signed'
        doc.l10n_xma_einvoice_numero = UUID
        doc._infile_run(lambda: (b'<Cancel/>', {}), cancel=True)
        self.assertEqual(doc.l10n_xma_einvoice_status, 'signed')
        self.assertEqual(doc.l10n_xma_einvoice_numero, UUID)

    def test_successful_cancellation_and_chatter_failure_keep_result(self):
        doc = FakeDocument(Mock(side_effect=[response({'resultado': True, 'archivo': 'SIGNED'}), response({'resultado': True})]))
        doc.l10n_xma_einvoice_status = 'signed'
        doc.l10n_xma_einvoice_numero = UUID
        doc.message_post.side_effect = RuntimeError('chatter unavailable')
        action = doc._infile_run(lambda: (b'<Cancel/>', {}), cancel=True)
        self.assertEqual(doc.l10n_xma_einvoice_status, 'canceled')
        self.assertEqual(doc.infile_vitec_state, 'done')
        self.assertEqual(doc.l10n_xma_einvoice_numero, UUID)
        self.assertEqual(action['params']['type'], 'success')
        with self.assertRaises(UserError):
            doc._infile_run(prepare)

    def test_pending_prevents_both_cancellation_and_certification(self):
        for cancel in (True, False):
            doc = FakeDocument(Mock())
            doc.infile_vitec_state = 'pending'
            with self.assertRaises(UserError):
                doc._infile_run(prepare, cancel=cancel)
            doc.post.assert_not_called()

    def test_payment_entrypoints_return_notification(self):
        payment = Mock()
        payment.l10n_xma_payment_item_ids = ['line']
        payment.move_id.send_json_gtm.return_value = {'tag': 'display_notification'}
        self.assertEqual(Payment.button_send_json_gtm(payment), {'tag': 'display_notification'})
        payment.move_id.send_json_gtm.assert_called_once_with(['line'], payment=payment)

    def test_draft_cannot_send(self):
        move = Mock(state='draft')
        with self.assertRaises(UserError):
            Move.send_json_gtm(move)
        move._infile_run.assert_not_called()

    def test_credentials_come_from_document_company(self):
        doc = types.SimpleNamespace(company_id=types.SimpleNamespace(
            country_id=types.SimpleNamespace(code='GT'), vat='12345-K', email='test@example.invalid',
            xma_infile_user='COMPANY-TWO', xma_token_signer='SIGNER-TWO', xma_api_key='API-TWO',
            infile_vitec_sign_url=transport.SIGN_URL, infile_vitec_certify_url=transport.CERTIFY_URL,
            infile_vitec_cancel_url=transport.CANCEL_URL))
        selected = Document._infile_client(doc)
        self.assertEqual(selected.user, 'COMPANY-TWO')
        self.assertEqual(selected.api_key, 'API-TWO')
        self.assertEqual(selected.nit, '12345K')


if __name__ == '__main__':
    unittest.main()
