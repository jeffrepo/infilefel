"""INFILE's two-step protocol, shared by certification and cancellation.

No Odoo dependency, automatic retry, MQTT transport or credential logging.
"""
import base64
import re
from urllib.parse import urlsplit
from uuid import UUID

import requests


SIGN_URL = 'https://signer-emisores.feel.com.gt/sign_solicitud_firmas/firma_xml'
CERTIFY_URL = 'https://certificador.feel.com.gt/fel/certificacion/v2/dte/'
CANCEL_URL = 'https://certificador.feel.com.gt/fel/anulacion/v2/dte/'


def validate_url(url):
    parts = urlsplit(url or '')
    if (parts.scheme != 'https' or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment):
        raise ValueError('Configure una URL HTTPS sin usuario, contraseña ni parámetros.')
    return url


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {
            str(key): ('[OMITIDO]' if re.search(
                r'llave|token|password|secret|archivo|xml|authorization', str(key), re.I
            ) else redact(item, secrets))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(str(secret), '[OMITIDO]')
        return value[:16000]
    return value


class InfileError(Exception):
    def __init__(self, diagnostic, uncertain=False):
        self.diagnostic = diagnostic
        self.uncertain = uncertain
        super().__init__(diagnostic['local_code'])


class InfileClient:
    def __init__(self, *, user, signer_key, api_key, nit, email,
                 sign_url=SIGN_URL, certify_url=CERTIFY_URL, cancel_url=CANCEL_URL,
                 post=None):
        self.user, self.signer_key, self.api_key = user, signer_key, api_key
        self.nit = nit.replace('-', '').replace(' ', '')
        self.email = email or ''
        self.sign_url = validate_url(sign_url)
        self.certify_url = validate_url(certify_url)
        self.cancel_url = validate_url(cancel_url)
        self.post = post or requests.post

    def _request(self, stage, url, payload, headers, identifier):
        diagnostic = {'stage': stage, 'url': url, 'identifier': identifier}
        can_have_issued = stage != 'firma'
        try:
            response = self.post(url, json=payload, headers=headers,
                                 timeout=(10, 60), allow_redirects=False)
        except requests.RequestException as error:
            diagnostic.update(local_code='INFILE_TRANSPORT_ERROR',
                              exception_type=type(error).__name__)
            raise InfileError(diagnostic, uncertain=can_have_issued) from error
        diagnostic['http_status'] = response.status_code
        try:
            result = response.json()
        except ValueError as error:
            diagnostic.update(local_code='INFILE_INVALID_RESPONSE',
                              response=redact(response.text, (self.signer_key, self.api_key)))
            raise InfileError(diagnostic, uncertain=can_have_issued) from error
        diagnostic['response'] = redact(result, (self.signer_key, self.api_key))
        if not 200 <= response.status_code < 300 or not isinstance(result, dict):
            diagnostic['local_code'] = 'INFILE_HTTP_ERROR'
            raise InfileError(diagnostic, uncertain=can_have_issued)
        if result.get('resultado') is not True:
            diagnostic['local_code'] = 'INFILE_REJECTED'
            # A missing outcome or duplicate warning requires reconciliation.
            duplicate = re.search(r'duplicad|ya existe|ya fue|previamente', str(diagnostic['response']), re.I)
            uncertain = can_have_issued and (result.get('resultado') is not False or bool(duplicate))
            raise InfileError(diagnostic, uncertain=uncertain)
        diagnostic['local_code'] = 'INFILE_OK'
        return result, diagnostic

    def submit(self, xml, identifier, cancel=False):
        signed, sign_diagnostic = self._request('firma', self.sign_url, {
            'llave': self.signer_key, 'codigo': self.nit, 'alias': self.user,
            'es_anulacion': 'S' if cancel else 'N',
            'archivo': base64.b64encode(xml).decode('ascii'),
        }, {'Content-Type': 'application/json'}, identifier)
        if not isinstance(signed.get('archivo'), str) or not signed['archivo']:
            sign_diagnostic['local_code'] = 'INFILE_MISSING_SIGNED_XML'
            raise InfileError(sign_diagnostic)
        result, diagnostic = self._request(
            'anulacion' if cancel else 'certificacion',
            self.cancel_url if cancel else self.certify_url,
            {'nit_emisor': self.nit, 'correo_copia': self.email, 'xml_dte': signed['archivo']},
            {'Content-Type': 'application/json', 'USUARIO': self.user,
             'LLAVE': self.api_key, 'IDENTIFICADOR': identifier}, identifier,
        )
        diagnostic['signature_http_status'] = sign_diagnostic['http_status']
        if not cancel and any(not result.get(key) for key in ('uuid', 'serie', 'numero')):
            diagnostic['local_code'] = 'INFILE_MISSING_CERTIFICATION_FIELDS'
            raise InfileError(diagnostic, uncertain=True)
        if not cancel:
            try:
                UUID(str(result['uuid']))
                if not isinstance(result['serie'], str) or not str(result['numero']).isdigit():
                    raise ValueError('invalid series/number')
            except ValueError as error:
                diagnostic['local_code'] = 'INFILE_INVALID_CERTIFICATION_FIELDS'
                raise InfileError(diagnostic, uncertain=True) from error
        return result, diagnostic
