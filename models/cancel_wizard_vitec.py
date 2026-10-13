from odoo import models, _
from odoo.exceptions import UserError


class CancelMotiveWizard(models.TransientModel):
    _inherit = 'xma.cancel_motive.wizard'

    def action_confirm(self):
        self.ensure_one()
        if self.env.context.get('active_model') not in (None, 'account.move'):
            raise UserError(_('Abra la anulación desde la factura.'))
        invoice = self.env['account.move'].browse(self.env.context.get('active_id')).exists()
        if not invoice or not self.l10n_xma_cancel_motive:
            raise UserError(_('Seleccione la factura y complete el motivo de cancelación.'))
        invoice.write({'l10n_xma_cancel_motive': self.l10n_xma_cancel_motive})
        return invoice.button_cancel_json_gtm()
