import base64
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

import requests


def load_module(name):
    path = Path(__file__).resolve().parents[1] / 'models' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transport = load_module('infile_transport')
xml_tools = load_module('vitec_xml')
UUID = '9233BF7F-BEFA-40A0-B781-71DC85006FC9'


def response(data, status=200):
    result = Mock(status_code=status, text=json.dumps(data))
    result.json.return_value = data
    return result


def client(post):
    return transport.InfileClient(user='TEST-USER', signer_key='TEST-SIGNER-KEY',
                                 api_key='TEST-API-KEY', nit='12345-K', email='', post=post)


class TransportTests(unittest.TestCase):
    def test_two_step_protocol_and_timeouts(self):
        post = Mock(side_effect=[response({'resultado': True, 'archivo': 'SIGNED'}),
                                 response({'resultado': True, 'uuid': UUID, 'serie': '9233BF7F', 'numero': 3204071584})])
        result, diagnostic = client(post).submit(b'<XML/>', 'VTC-test')
        signature, certification = post.call_args_list
        self.assertEqual(signature.args, (transport.SIGN_URL,))
        self.assertEqual(signature.kwargs['json']['archivo'], base64.b64encode(b'<XML/>').decode())
        self.assertEqual(signature.kwargs['json']['es_anulacion'], 'N')
        self.assertEqual(signature.kwargs['json']['codigo'], '12345K')
        self.assertEqual(certification.args, (transport.CERTIFY_URL,))
        self.assertEqual(certification.kwargs['headers']['IDENTIFICADOR'], 'VTC-test')
        self.assertEqual(certification.kwargs['json']['xml_dte'], 'SIGNED')
        self.assertEqual(certification.kwargs['timeout'], (10, 60))
        self.assertFalse(certification.kwargs['allow_redirects'])
        self.assertEqual(diagnostic['http_status'], 200)
        self.assertEqual(result['uuid'], UUID)

    def test_cancellation_endpoint_and_flag(self):
        post = Mock(side_effect=[response({'resultado': True, 'archivo': 'SIGNED'}), response({'resultado': True})])
        client(post).submit(b'<Cancel/>', 'cancel-test', cancel=True)
        self.assertEqual(post.call_args_list[0].kwargs['json']['es_anulacion'], 'S')
        self.assertEqual(post.call_args.args, (transport.CANCEL_URL,))

    def test_signer_rejection_never_certifies(self):
        post = Mock(return_value=response({'resultado': False, 'descripcion': 'Token inválido', 'codigo': 10}))
        with self.assertRaises(transport.InfileError) as caught:
            client(post).submit(b'<XML/>', 'test')
        self.assertEqual(post.call_count, 1)
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(caught.exception.diagnostic['response']['codigo'], 10)

    def test_rejection_keeps_provider_details_but_redacts_credentials(self):
        post = Mock(side_effect=[response({'resultado': True, 'archivo': 'SIGNED'}), response({
            'resultado': False, 'cantidad_errores': 1,
            'descripcion_errores': [{'codigo': 'SAT-TEST', 'mensaje_error': 'Error TEST-API-KEY'}],
            'llave': 'TEST-SIGNER-KEY', 'xml_dte': 'private xml',
        })])
        with self.assertRaises(transport.InfileError) as caught:
            client(post).submit(b'<XML/>', 'test')
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic['http_status'], 200)
        self.assertIn('SAT-TEST', json.dumps(diagnostic))
        self.assertNotIn('TEST-API-KEY', json.dumps(diagnostic))
        self.assertNotIn('TEST-SIGNER-KEY', json.dumps(diagnostic))
        self.assertNotIn('private xml', json.dumps(diagnostic))
        self.assertFalse(caught.exception.uncertain)

    def test_certification_timeout_is_uncertain_without_retry(self):
        post = Mock(side_effect=[response({'resultado': True, 'archivo': 'SIGNED'}), requests.ReadTimeout()])
        with self.assertRaises(transport.InfileError) as caught:
            client(post).submit(b'<XML/>', 'test')
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(caught.exception.diagnostic['exception_type'], 'ReadTimeout')

    def test_signer_timeout_does_not_mean_certification_pending(self):
        post = Mock(side_effect=requests.ReadTimeout())
        with self.assertRaises(transport.InfileError) as caught:
            client(post).submit(b'<XML/>', 'test')
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(post.call_count, 1)

    def test_ambiguous_responses_block_new_certification(self):
        invalid_json = Mock(status_code=502, text='upstream unavailable')
        invalid_json.json.side_effect = ValueError()
        cases = [invalid_json, response({'resultado': False}, status=503),
                 response({'resultado': 'true'}), response({'resultado': True}),
                 response({'resultado': True, 'uuid': 'invalid', 'serie': 'ABC', 'numero': 1}),
                 response({'resultado': False, 'descripcion': 'Documento ya existe'}),
                 response({'resultado': False}, status=302)]
        for bad in cases:
            with self.subTest(bad=bad):
                post = Mock(side_effect=[response({'resultado': True, 'archivo': 'SIGNED'}), bad])
                with self.assertRaises(transport.InfileError) as caught:
                    client(post).submit(b'<XML/>', 'test')
                self.assertTrue(caught.exception.uncertain)
                self.assertEqual(post.call_count, 2)

    def test_missing_signed_xml_stops_before_certification(self):
        post = Mock(return_value=response({'resultado': True}))
        with self.assertRaises(transport.InfileError) as caught:
            client(post).submit(b'<XML/>', 'test')
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(post.call_count, 1)

    def test_https_configuration(self):
        for url in ('http://example.com', 'https://u:p@example.com', 'https://example.com/?key=secret'):
            with self.assertRaises(ValueError):
                transport.validate_url(url)


class XMLTests(unittest.TestCase):
    def test_namespaces_lists_escaping_and_omitted_empty_nodes(self):
        data = [{'dte:GTDocumento': {'@xmlns:dte': xml_tools.DTE, '@Version': '0.1',
                                   'dte:SAT': {'dte:Frases': {'dte:Frase': [
                                       {'@TipoFrase': '1', '@CodigoEscenario': 1},
                                       {'@TipoFrase': '4', '@CodigoEscenario': 19}]},
                                       'dte:Descripcion': 'A & B <C>', 'dte:Complementos': []}}}]
        xml = xml_tools.serialize(data)
        root = xml_tools.etree.fromstring(xml)
        ns = {'dte': xml_tools.DTE}
        self.assertEqual(root.find('.//dte:Descripcion', ns).text, 'A & B <C>')
        self.assertEqual(len(root.findall('.//dte:Frase', ns)), 2)
        self.assertIsNone(root.find('.//dte:Complementos', ns))
        self.assertIsNone(root.find('.//dte:Adenda', ns))

    def test_cancellation_preserves_original_timestamp_and_receiver(self):
        xml = xml_tools.cancellation_xml(uuid=UUID, nit='12345K', receiver='CF',
                                          emission='2026-09-29T09:04:14-06:00',
                                          date='2026-10-13T12:00:00-06:00', reason='A & B')
        node = xml_tools.etree.fromstring(xml).find('.//{%s}DatosGenerales' % xml_tools.CANCEL)
        self.assertEqual(node.get('FechaEmisionDocumentoAnular'), '2026-09-29T09:04:14-06:00')
        self.assertEqual(node.get('NumeroDocumentoAAnular'), UUID)
        self.assertEqual(node.get('MotivoAnulacion'), 'A & B')

    def test_wrong_historic_xml_rejected(self):
        with self.assertRaises(ValueError):
            xml_tools.original_metadata(b'<dte:GTDocumento xmlns:dte="http://www.sat.gob.gt/dte/fel/0.2.0"/>', UUID)


if __name__ == '__main__':
    unittest.main()
