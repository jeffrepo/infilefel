# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class InfileFelFraseExtra(models.Model):
    _name = 'infilefel.frase.extra'
    _description = 'Frase FEL adicional para facturas'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Nombre', required=True)
    codigo_escenario = fields.Integer(string='Código de escenario', required=True)
    tipo_frase = fields.Integer(string='Tipo de frase', required=True)
    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True,
        default=lambda self: self.env.company, index=True,
    )
    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        (
            'codigo_escenario_positivo',
            'CHECK(codigo_escenario > 0)',
            'El código de escenario debe ser un entero mayor que cero.',
        ),
        (
            'tipo_frase_positivo',
            'CHECK(tipo_frase > 0)',
            'El tipo de frase debe ser un entero mayor que cero.',
        ),
        (
            'escenario_tipo_company_uniq',
            'UNIQUE(company_id, codigo_escenario, tipo_frase)',
            'Ya existe una frase FEL con este código de escenario y tipo en la compañía.',
        ),
    ]

    @api.depends('name', 'codigo_escenario', 'tipo_frase')
    def _compute_display_name(self):
        for frase in self:
            frase.display_name = _(
                '%(name)s (escenario %(codigo)s, tipo %(tipo)s)',
                name=frase.name or '', codigo=frase.codigo_escenario,
                tipo=frase.tipo_frase,
            )

    def _check_used_on_invoices(self):
        # Include all companies and states so changing the catalog cannot alter
        # the meaning of a phrase already selected on an invoice.
        if self.env['account.move'].sudo().search_count([
            ('fel_frase_extra_ids', 'in', self.ids),
        ], limit=1):
            raise UserError(_(
                'Esta frase FEL ya está asignada a una factura. Puede cambiar '
                'su nombre o archivarla; para usar otros códigos, cree una nueva frase.'
            ))

    def write(self, vals):
        if {'codigo_escenario', 'tipo_frase', 'company_id'} & vals.keys():
            self.check_access('write')
            self._check_used_on_invoices()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_used_on_invoices(self):
        self._check_used_on_invoices()
