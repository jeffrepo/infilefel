"""Lossless conversion of Vitec's XML-shaped dict (attributes use @)."""
from copy import deepcopy
from lxml import etree

DTE = 'http://www.sat.gob.gt/dte/fel/0.2.0'
CANCEL = 'http://www.sat.gob.gt/dte/fel/0.1.0'


def _qname(name, namespaces):
    if ':' in name:
        prefix, local = name.split(':', 1)
        return '{%s}%s' % (namespaces[prefix], local)
    return name


def _element(name, value, namespaces):
    local_ns = {}
    if isinstance(value, dict):
        local_ns = {key[7:]: val for key, val in value.items() if key.startswith('@xmlns:')}
    namespaces = dict(namespaces, **local_ns)
    node = etree.Element(_qname(name, namespaces), nsmap=local_ns or None)
    if isinstance(value, dict):
        for key, val in value.items():
            if key.startswith('@xmlns:'):
                continue
            if key.startswith('@'):
                if val is not None and val is not False:
                    node.set(_qname(key[1:], namespaces), str(val))
            elif key == '#text':
                node.text = str(val)
            else:
                for child in val if isinstance(val, list) else [val]:
                    if child is not False and child is not None:
                        node.append(_element(key, child, namespaces))
    elif value is not None:
        node.text = str(value)
    return node


def serialize(data):
    if not isinstance(data, list) or len(data) != 1 or len(data[0]) != 1:
        raise ValueError('Se esperaba exactamente un documento FEL de Vitec.')
    name, value = next(iter(data[0].items()))
    return etree.tostring(_element(name, value, {}), encoding='UTF-8', xml_declaration=True)


def prepare_document(payload, origin=None):
    data = deepcopy(payload['data'])
    sat = data[0]['dte:GTDocumento']['dte:SAT']
    emission = sat['dte:DTE']['dte:DatosEmision']
    if origin:
        references = emission['dte:Complementos']['dte:Complemento']['cno:ReferenciasNota']
        references['@SerieDocumentoOrigen'] = origin['serie']
        references['@NumeroDocumentoOrigen'] = origin['numero']
        references['@NumeroAutorizacionDocumentoOrigen'] = origin['uuid']
    metadata = {
        'emission': emission['dte:DatosGenerales']['@FechaHoraEmision'],
        'receiver': emission['dte:Receptor']['@IDReceptor'],
        'issuer': emission['dte:Emisor']['@NITEmisor'],
        'phrases': emission.get('dte:Frases') or {},
        'adenda': sat.get('dte:Adenda') or {},
    }
    return serialize(data), metadata


def cancellation_xml(*, uuid, nit, receiver, emission, date, reason):
    return serialize([{'dte:GTAnulacionDocumento': {
        '@xmlns:dte': CANCEL, '@Version': '0.1',
        'dte:SAT': {'dte:AnulacionDTE': {
            '@ID': 'DatosCertificados',
            'dte:DatosGenerales': {
                '@ID': 'DatosAnulacion', '@NumeroDocumentoAAnular': uuid,
                '@NITEmisor': nit, '@IDReceptor': receiver,
                '@FechaEmisionDocumentoAnular': emission, '@FechaHoraAnulacion': date,
                '@MotivoAnulacion': reason,
            },
        }},
    }}])


def original_metadata(xml, expected_uuid):
    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {'dte': DTE}
    emission = root.find('.//dte:DatosEmision/dte:DatosGenerales', ns)
    receiver = root.find('.//dte:DatosEmision/dte:Receptor', ns)
    issuer = root.find('.//dte:DatosEmision/dte:Emisor', ns)
    authorization = root.find('.//dte:Certificacion/dte:NumeroAutorizacion', ns)
    if authorization is None or (authorization.text or '').strip().upper() != expected_uuid.strip().upper():
        raise ValueError('El UUID del XML certificado no corresponde a este documento.')
    if emission is None or receiver is None or issuer is None:
        raise ValueError('El XML no contiene los datos originales de emisión.')
    return (emission.get('FechaHoraEmision'), receiver.get('IDReceptor'), issuer.get('NITEmisor'))
