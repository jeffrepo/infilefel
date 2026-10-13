import base64
from datetime import datetime

from lxml import etree
from odoo import fields, models, _
from odoo.exceptions import UserError

from .vitec_xml import prepare_document, cancellation_xml, original_metadata


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'infile.vitec.document']

    def button_send_json_gtm(self):
        self.ensure_one()
        return self.send_json_gtm()

    def send_json_gtm(self, itemlines=False, payment=False):
        self.ensure_one()
        target = payment or self
        if payment and payment.move_id != self:
            raise UserError(_('El pago no corresponde al asiento que se intenta certificar.'))
        if self.state != 'posted':
            raise UserError(_('Publique el documento antes de timbrarlo.'))
        return target._infile_run(lambda: self._infile_prepare(itemlines, payment))

    def _infile_prepare(self, itemlines=False, payment=False):
        target = payment or self
        doc_type = target.l10n_latam_document_type_id.code
        if not doc_type:
            raise UserError(_('Seleccione el tipo de documento FEL.'))
        origin = None
        if doc_type in ('NCRE', 'NDEB'):
            original = self.reversed_entry_id if doc_type == 'NCRE' else self.debit_origin_id
            if not original or not all((original.l10n_xma_einvoice_numero,
                                       original.l10n_xma_uuid_invoice,
                                       original.l10n_xma_einvoice_serie,
                                       original.l10n_xma_date_post)):
                raise UserError(_('La nota requiere una factura de origen certificada con fecha, serie, número y UUID.'))
            origin = {'serie': original.l10n_xma_uuid_invoice,
                      'numero': original.l10n_xma_einvoice_serie,
                      'uuid': original.l10n_xma_einvoice_numero}
        # Keep Vitec's taxes, phrases, FCAM complement and any installed extension.
        # Fix the timezone independently of the operator's display preferences.
        move = self.with_context(tz='America/Guatemala')
        payload = move.generate_json_l10n_gtm(itemlines, payment)
        try:
            emission = payload['data'][0]['dte:GTDocumento']['dte:SAT']['dte:DTE']['dte:DatosEmision']
            emission['dte:DatosGenerales']['@FechaHoraEmision'] = fields.Datetime.context_timestamp(
                move, move.l10n_xma_date_post).isoformat(timespec='seconds')
            if origin:
                reference = emission['dte:Complementos']['dte:Complemento']['cno:ReferenciasNota']
                reference['@FechaEmisionDocumentoOrigen'] = (
                    original.infile_vitec_emission[:10] if original.infile_vitec_emission
                    else fields.Datetime.context_timestamp(move, original.l10n_xma_date_post).strftime('%Y-%m-%d'))
            return prepare_document(payload, origin=origin)
        except (ValueError, KeyError, TypeError) as error:
            raise UserError(_('No fue posible convertir el documento de Vitec a XML: %s') % error) from error

    def button_cancel_json_gtm(self):
        self.ensure_one()
        return self.cancel_json_gtm()

    def cancel_json_gtm(self, payment=False):
        self.ensure_one()
        if payment and payment.move_id != self:
            raise UserError(_('El pago no corresponde al asiento que se intenta anular.'))
        target = payment or self
        return target._infile_run(lambda: self._infile_prepare_cancel(target), cancel=True)

    def _infile_prepare_cancel(self, target):
        emission, receiver, issuer = (target.infile_vitec_emission,
                                      target.infile_vitec_receiver, target.infile_vitec_issuer)
        if not all((emission, receiver, issuer)):
            # Historic Xmarts invoices: require the original XML, because the
            # displayed timestamp/partner may differ from what was certified.
            saved_xml = target.infile_vitec_certified_xml
            if not saved_xml and target._name == 'account.move':
                saved_xml = target.l10n_xma_xml_ar
            if not saved_xml:
                raise UserError(_(
                    'Para anular este documento histórico se necesita su XML certificado original. '
                    'Cárguelo en el campo Invoice Xml de la factura antes de continuar.'
                ))
            try:
                emission, receiver, issuer = original_metadata(
                    base64.b64decode(saved_xml), target.l10n_xma_einvoice_numero)
            except (ValueError, etree.XMLSyntaxError) as error:
                raise UserError(_('No se pudieron leer los datos del XML original: %s') % error) from error
        if not all((emission, receiver, issuer)):
            raise UserError(_('El XML original no contiene fecha, receptor y emisor completos.'))
        if issuer.replace('-', '').replace(' ', '') != target.company_id.vat.replace('-', '').replace(' ', ''):
            raise UserError(_('El emisor del documento original no corresponde al NIT de la compañía.'))
        now = fields.Datetime.context_timestamp(self.with_context(tz='America/Guatemala'), datetime.utcnow())
        return cancellation_xml(uuid=target.l10n_xma_einvoice_numero,
                                nit=issuer, receiver=receiver, emission=emission,
                                date=now.isoformat(timespec='seconds'),
                                reason=target.l10n_xma_cancel_motive), {}
