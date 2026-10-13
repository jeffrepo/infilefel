from odoo import fields, models

from .infile_transport import SIGN_URL, CERTIFY_URL, CANCEL_URL


class ResCompany(models.Model):
    _inherit = 'res.company'

    infile_vitec_sign_url = fields.Char('URL de firma INFILE', default=SIGN_URL, required=True)
    infile_vitec_certify_url = fields.Char('URL de certificación INFILE', default=CERTIFY_URL, required=True)
    infile_vitec_cancel_url = fields.Char('URL de anulación INFILE', default=CANCEL_URL, required=True)
