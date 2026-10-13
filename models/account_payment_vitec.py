from odoo import models


class AccountPayment(models.Model):
    _name = 'account.payment'
    _inherit = ['account.payment', 'infile.vitec.document']

    def button_send_json_gtm(self):
        self.ensure_one()
        return self.move_id.send_json_gtm(self.l10n_xma_payment_item_ids, payment=self)

    def button_cancel_json_gtm(self):
        self.ensure_one()
        return self.move_id.cancel_json_gtm(payment=self)
