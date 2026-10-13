"""Exercise the real installed Vitec generator with synthetic accounting data.

Set VITEC_SOURCE_DIR to the Vitec repository. No database, keys or HTTP required.
"""
import ast
from datetime import datetime, date, timezone, timedelta
import logging
import os
from pathlib import Path
import re
from types import SimpleNamespace as NS
import unittest

from test_transport import xml_tools, UUID

SOURCE_DIR = os.environ.get('VITEC_SOURCE_DIR')


def phrase(kind, scenario):
    return NS(typeprase_code=str(kind), scenario_code=scenario)


class PhraseRepository:
    records = [phrase(1, 1), phrase(4, 1), phrase(4, 19)]

    def sudo(self):
        return self

    def search(self, domain):
        return [rec for rec in self.records if all(
            getattr(rec, key) == val if op == '=' else getattr(rec, key) in val
            for key, op, val in domain)]


class Environment:
    user = NS(tz='America/Guatemala')

    def __getitem__(self, name):
        if name == 'l10n_xma.fel_phrase':
            return PhraseRepository()
        if name == 'account.tax':
            return NS(search=lambda *a, **k: NS(l10n_xma_edi_tax_type_id=NS(name='IVA'), amount=12))
        raise AssertionError(name)

    def ref(self, xmlid):
        assert xmlid == 'base.USD'
        return NS(id=2)


class Invoice:
    env = Environment()

    def __init__(self, code='FACT', country='GT', currency='GTQ'):
        self.id = 16661
        self.move_type = 'out_refund' if code == 'NCRE' else 'out_invoice'
        self.l10n_latam_document_type_id = NS(code=code, l10n_xma_branch='1')
        self.currency_id = NS(name=currency, id=2 if currency == 'USD' else 1, decimal_places=2)
        self.partner_id = NS(vat='CF', name='Cliente & prueba', email='test@example.invalid',
                             street='Ciudad', zip='01001', city='Guatemala', state_id=NS(name='Guatemala'),
                             country_id=NS(code=country), l10n_latam_identification_type_id=NS(name='NIT'))
        self.company_id = NS(id=1, vat='12345K', email='test@example.invalid', street='Ciudad', zip='01001',
                             city='Guatemala', state_id=NS(name='Guatemala'), country_id=NS(code='GT'),
                             partner_id=NS(l10n_xma_taxpayer_type_id=NS(code='GEN'), commercial_name='TEST', name='TEST'),
                             l10n_xma_phrase_ids=[phrase(1, 2), phrase(2, 1)], uuid_client='unused',
                             xma_infile_user='TEST', xma_token_signer='TEST', xma_api_key='TEST', xma_api_url='unused')
        self.amount_total = self.amount_untaxed = 112.0
        self.invoice_date = date(2026, 10, 13)
        self.invoice_date_due = date(2026, 11, 13)
        self.ref = 'Corrección'
        self.reversed_entry_id = self.debit_origin_id = NS(
            l10n_xma_date_post=datetime(2026, 9, 29, 15, 4, 14),
            infile_vitec_emission='2026-09-29T09:04:14-06:00',
            l10n_xma_einvoice_numero=UUID, l10n_xma_uuid_invoice='9233BF7F',
            l10n_xma_einvoice_serie='3204071584')
        self.invoice_line_ids = [NS(product_id=NS(detailed_type='consu', display_name='A & B', name='A & B'),
                                   quantity=1, price_unit=112.0, discount=0, price_subtotal=112.0)]

    def __iter__(self):
        return iter([self])

    def with_context(self, **kwargs):
        return self

    def xma_compute_base_line_taxes(self, line):
        return {'taxes': [{'id': 1, 'amount': 12.0, 'base': 100.0}]}


@unittest.skipUnless(SOURCE_DIR, 'Set VITEC_SOURCE_DIR to test the actual Vitec generator')
class VitecGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(SOURCE_DIR) / 'xmarts/changing_generate_json_l10n_gtm/changing_generate_json_l10n_gtm/models/account_move.py'
        tree = ast.parse(source.read_text())
        klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'AccountMove')
        method = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == 'generate_json_l10n_gtm')
        namespace = {'datetime': datetime, 're': re, '_logger': logging.getLogger(__name__),
                     'fields': NS(Datetime=NS(context_timestamp=lambda rec, dt:
                                              dt.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-6)))))}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        cls.generate = staticmethod(namespace['generate_json_l10n_gtm'])

    def document(self, code='FACT', country='GT', currency='GTQ', payment=False):
        move = Invoice(code, country, currency)
        target = NS(id=71, l10n_latam_document_type_id=move.l10n_latam_document_type_id, amount=112) if payment else False
        payload = self.generate(move, move.invoice_line_ids if payment else False, target)
        origin = {'serie': '9233BF7F', 'numero': '3204071584', 'uuid': UUID} if code in ('NCRE', 'NDEB') else None
        xml, metadata = xml_tools.prepare_document(payload, origin)
        return xml_tools.etree.fromstring(xml), metadata, payload

    def phrases(self, root):
        return [(node.get('TipoFrase'), node.get('CodigoEscenario')) for node in root.findall('.//{%s}Frase' % xml_tools.DTE)]

    def test_domestic_fact_and_fcam_use_company_phrases_without_adenda(self):
        for code in ('FACT', 'FCAM'):
            root, metadata, _ = self.document(code)
            self.assertEqual(self.phrases(root), [('1', '2'), ('2', '1')])
            self.assertIsNone(root.find('.//{%s}Adenda' % xml_tools.DTE))
            self.assertFalse(metadata['adenda'])

    def test_export_fact_and_credit_note_use_catalogue_scenario_one(self):
        for code in ('FACT', 'NCRE'):
            root, _, _ = self.document(code, country='US')
            self.assertEqual(self.phrases(root), [('1', '1'), ('4', '1')])

    def test_domestic_usd_adds_type_four_scenario_nineteen(self):
        root, _, _ = self.document(currency='USD')
        self.assertEqual(self.phrases(root), [('4', '19'), ('1', '2'), ('2', '1')])

    def test_receipt_advance_uses_type_nine_scenario_six(self):
        root, _, payload = self.document('RANT', payment=True)
        self.assertEqual(self.phrases(root), [('9', '6')])
        self.assertTrue(payload['payment'])
        self.assertEqual(payload['id'], 71)

    def test_special_invoice_and_credit_receipt_omit_phrases(self):
        for code in ('FESP', 'NABN'):
            root, _, _ = self.document(code)
            self.assertEqual(self.phrases(root), [])
            self.assertIsNone(root.find('.//{%s}Frases' % xml_tools.DTE))

    def test_credit_and_debit_note_references_use_confirmed_mapping(self):
        for code in ('NCRE', 'NDEB'):
            root, _, original_payload = self.document(code)
            references = root.find('.//{http://www.sat.gob.gt/face2/ComplementoReferenciaNota/0.1.0}ReferenciasNota')
            self.assertEqual(references.get('SerieDocumentoOrigen'), '9233BF7F')
            self.assertEqual(references.get('NumeroDocumentoOrigen'), '3204071584')
            self.assertEqual(references.get('NumeroAutorizacionDocumentoOrigen'), UUID)
            old_ref = original_payload['data'][0]['dte:GTDocumento']['dte:SAT']['dte:DTE']['dte:DatosEmision']['dte:Complementos']['dte:Complemento']['cno:ReferenciasNota']
            self.assertEqual(old_ref['@NumeroDocumentoOrigen'], '9233BF7F')  # Input was not mutated.

    def test_fcam_keeps_vitec_due_date_and_installment(self):
        root, _, _ = self.document('FCAM')
        ns = '{http://www.sat.gob.gt/dte/fel/CompCambiaria/0.1.0}'
        self.assertEqual(root.find('.//' + ns + 'FechaVencimiento').text, '2026-11-13')
        self.assertEqual(root.find('.//' + ns + 'MontoAbono').text, '112.0')

    def test_adapter_prepares_actual_generator_and_original_reference(self):
        from test_document import Move
        move = Invoice('NCRE')
        move.generate_json_l10n_gtm = lambda *args: self.generate(move, *args)
        xml, metadata = Move._infile_prepare(move)
        self.assertTrue(metadata['emission'].endswith('-06:00'))
        root = xml_tools.etree.fromstring(xml)
        reference = root.find('.//{http://www.sat.gob.gt/face2/ComplementoReferenciaNota/0.1.0}ReferenciasNota')
        self.assertEqual(reference.get('FechaEmisionDocumentoOrigen'), '2026-09-29')
        self.assertEqual(reference.get('SerieDocumentoOrigen'), '9233BF7F')


if __name__ == '__main__':
    unittest.main()
