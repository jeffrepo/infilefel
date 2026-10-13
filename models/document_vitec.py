import base64
import json
import logging
from uuid import uuid4

from lxml import etree
from markupsafe import Markup
from psycopg2 import OperationalError, sql

from odoo import fields, models, _
from odoo.exceptions import UserError

from .infile_transport import InfileClient, InfileError
from .vitec_xml import original_metadata

_logger = logging.getLogger(__name__)


class InfileVitecDocument(models.AbstractModel):
    _name = 'infile.vitec.document'
    _description = 'Seguimiento de solicitudes directas a INFILE'

    infile_vitec_state = fields.Selection([
        ('pending', 'Solicitud iniciada'), ('uncertain', 'Resultado por confirmar'),
        ('failed', 'Rechazada / no enviada'), ('done', 'Completada'),
    ], string='Estado de solicitud INFILE', readonly=True, copy=False)
    infile_vitec_operation = fields.Selection([
        ('certify', 'Certificación'), ('cancel', 'Anulación'),
    ], string='Operación INFILE', readonly=True, copy=False)
    infile_vitec_identifier = fields.Char('Identificador para soporte INFILE', readonly=True, copy=False)
    infile_vitec_diagnostic = fields.Text('Última respuesta INFILE', readonly=True, copy=False)
    infile_vitec_emission = fields.Char('Fecha de emisión enviada a INFILE', readonly=True, copy=False)
    infile_vitec_receiver = fields.Char('Receptor enviado a INFILE', readonly=True, copy=False)
    infile_vitec_issuer = fields.Char('Emisor enviado a INFILE', readonly=True, copy=False)
    infile_vitec_request_xml = fields.Binary('XML de la última solicitud', readonly=True, copy=False, attachment=True)
    infile_vitec_request_name = fields.Char(readonly=True, copy=False)
    infile_vitec_certified_xml = fields.Binary('XML certificado INFILE', readonly=True, copy=False, attachment=True)
    infile_vitec_certified_name = fields.Char(readonly=True, copy=False)

    def _infile_client(self):
        company = self.company_id
        if company.country_id.code != 'GT':
            raise UserError(_('El adaptador INFILE Vitec requiere una compañía de Guatemala.'))
        if not all((company.vat, company.xma_infile_user, company.xma_token_signer, company.xma_api_key)):
            raise UserError(_('Complete el NIT, usuario INFILE, Token Signer y llave API en la compañía.'))
        try:
            return InfileClient(
                user=company.xma_infile_user, signer_key=company.xma_token_signer,
                api_key=company.xma_api_key, nit=company.vat, email=company.email,
                sign_url=company.infile_vitec_sign_url,
                certify_url=company.infile_vitec_certify_url,
                cancel_url=company.infile_vitec_cancel_url,
            )
        except ValueError as error:
            raise UserError(str(error)) from error

    def _infile_lock(self):
        self.ensure_one()
        self.check_access_rights('write')
        self.check_access_rule('write')
        self.flush_recordset()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(sql.SQL('SELECT id FROM {} WHERE id = %s FOR UPDATE NOWAIT').format(
                    sql.Identifier(self._table)), [self.id])
        except OperationalError as error:
            raise UserError(_('Otro proceso está trabajando en este documento. Actualice la factura.')) from error
        self.invalidate_recordset()

    def _infile_check_operation(self, cancel):
        if self.infile_vitec_state in ('pending', 'uncertain'):
            raise UserError(_(
                'La solicitud %s está pendiente de confirmar. Consulte con INFILE antes de '
                'reenviar para evitar duplicados. El diagnóstico está en la pestaña INFILE directo.'
            ) % self.infile_vitec_identifier)
        if cancel:
            if self.l10n_xma_einvoice_status != 'signed' or not self.l10n_xma_einvoice_numero:
                raise UserError(_('Solo se puede anular un documento certificado.'))
            if not self.l10n_xma_cancel_motive:
                raise UserError(_('Complete el motivo de cancelación antes de anular.'))
        elif self.l10n_xma_einvoice_status in ('signed', 'canceled') or self.l10n_xma_einvoice_numero:
            raise UserError(_('Este documento ya tiene una certificación; no se volverá a timbrar.'))

    def _infile_run(self, prepare, cancel=False):
        """Persist intent before HTTP so an RPC retry cannot issue a second DTE.

        These entry points are explicit user buttons, never _post/write hooks.
        Unexpected failures leave the committed pending state for reconciliation.
        """
        self._infile_lock()
        self._infile_check_operation(cancel)
        client = self._infile_client()
        xml, metadata = prepare()
        identifier = 'VTC-' + uuid4().hex
        values = {
            'infile_vitec_identifier': identifier,
            'infile_vitec_state': 'pending',
            'infile_vitec_operation': 'cancel' if cancel else 'certify',
            'infile_vitec_request_xml': base64.b64encode(xml),
            'infile_vitec_request_name': '%s-%s.xml' % ('anulacion' if cancel else 'solicitud', identifier),
            'infile_vitec_diagnostic': json.dumps({
                'local_code': 'INFILE_REQUEST_STARTED', 'identifier': identifier,
                'started_at_utc': str(fields.Datetime.now()),
                'phrases': metadata.get('phrases'),
                'adenda_present': bool(metadata.get('adenda')),
            }, ensure_ascii=False, indent=2),
        }
        if not cancel:
            values.update(infile_vitec_emission=metadata['emission'],
                          infile_vitec_receiver=metadata['receiver'],
                          infile_vitec_issuer=metadata['issuer'])
        self.write(values)
        self.env.cr.commit()
        try:
            result, diagnostic = client.submit(xml, identifier, cancel=cancel)
        except InfileError as error:
            diagnostic = error.diagnostic
            values = {'infile_vitec_state': 'uncertain' if error.uncertain else 'failed'}
            if not cancel and not error.uncertain:
                values['l10n_xma_einvoice_status'] = 'failed'
            notification_type = 'warning' if error.uncertain else 'danger'
            message = _('Resultado por confirmar con INFILE.') if error.uncertain else _('INFILE no certificó la solicitud.')
        else:
            values = {'infile_vitec_state': 'done',
                      'l10n_xma_einvoice_status': 'canceled' if cancel else 'signed'}
            if not cancel:
                # Preserve the historical Vitec storage verified on FACT001218.
                values.update(l10n_xma_uuid_invoice=str(result['serie']),
                              l10n_xma_einvoice_serie=str(result['numero']),
                              l10n_xma_einvoice_numero=str(result['uuid']))
                certified = result.get('xml_certificado')
                if isinstance(certified, str) and certified:
                    try:
                        decoded = base64.b64decode(certified, validate=True)
                        original_metadata(decoded, str(result['uuid']))
                    except (ValueError, etree.XMLSyntaxError):
                        diagnostic['xml_warning'] = 'INFILE devolvió xml_certificado inválido; solicítelo con el UUID.'
                    else:
                        values.update(infile_vitec_certified_xml=certified,
                                      infile_vitec_certified_name='%s.xml' % result['uuid'])
                        if self._name == 'account.move':
                            values.update(l10n_xma_xml_ar=certified, l10n_xma_xml_name=values['infile_vitec_certified_name'])
            notification_type = 'success'
            message = _('Documento anulado por INFILE.') if cancel else _('Documento certificado por INFILE. UUID: %s') % result['uuid']
        diagnostic.update(finished_at_utc=str(fields.Datetime.now()), model=self._name,
                          record_id=self.id, company_id=self.company_id.id,
                          phrases=metadata.get('phrases'), adenda_present=bool(metadata.get('adenda')))
        details = json.dumps(diagnostic, ensure_ascii=False, indent=2)
        values['infile_vitec_diagnostic'] = details
        self.write(values)
        # The fiscal result must survive a chatter/attachment rendering failure.
        self.env.cr.commit()
        _logger.info('INFILE Vitec diagnostic: %s', details)
        try:
            with self.env.cr.savepoint():
                self.message_post(body=Markup('<p>%s</p><pre>%s</pre>') % (message, details),
                                  subtype_xmlid='mail.mt_note')
        except Exception:
            _logger.warning('INFILE Vitec: resultado guardado; no se pudo agregar el mensaje para %s', identifier)
        self.env.cr.commit()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('INFILE directo'), 'type': notification_type, 'sticky': True,
            'message': '%s\nHTTP: %s · %s\nIdentificador: %s\n%s' % (
                message, diagnostic.get('http_status', 'sin respuesta'), diagnostic['local_code'], identifier,
                json.dumps(diagnostic.get('response', {}), ensure_ascii=False)[:900]),
            'next': {'type': 'ir.actions.client', 'tag': 'reload'},
        }}
