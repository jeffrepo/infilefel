# -*- coding: utf-8 -*-

from lxml import etree

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user


DTE_NS = '{http://www.sat.gob.gt/dte/fel/0.2.0}'


@tagged('post_install', '-at_install')
class TestFelFrases(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.frase_model = cls.env['infilefel.frase.extra']
        cls.manager = new_test_user(
            cls.env, login='fel_frases_manager',
            groups='account.group_account_manager', company_id=cls.env.company.id,
        )
        cls.invoice_user = new_test_user(
            cls.env, login='fel_frases_invoice',
            groups='account.group_account_invoice', company_id=cls.env.company.id,
        )
        cls.other_company = cls.env['res.company'].create({'name': 'Otra compañía FEL'})

    def setUp(self):
        super().setUp()
        self.frase = self.frase_model.with_user(self.manager).create({
            'name': 'Frase adicional de prueba',
            'codigo_escenario': 1,
            'tipo_frase': 4,
            'company_id': self.env.company.id,
        })
        self.invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'company_id': self.env.company.id,
            'partner_id': self.partner_a.id,
            'journal_id': self.company_data['default_journal_sale'].id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'name': 'Producto de prueba',
                'quantity': 1,
                'price_unit': 100,
                'account_id': self.company_data['default_account_revenue'].id,
                'tax_ids': [Command.clear()],
            })],
        })

    def test_invoice_user_can_select_but_not_manage_catalog(self):
        user_frase = self.frase.with_user(self.invoice_user)
        self.assertEqual(user_frase.read(['tipo_frase'])[0]['tipo_frase'], 4)
        self.invoice.with_user(self.invoice_user).write({
            'fel_frase_extra_ids': [Command.link(self.frase.id)],
        })
        self.assertEqual(self.invoice.fel_frase_extra_ids, self.frase)
        with self.assertRaises(AccessError):
            user_frase.write({'name': 'Cambio no permitido'})
        with self.assertRaises(AccessError):
            user_frase.unlink()
        with self.assertRaises(AccessError):
            self.frase_model.with_user(self.invoice_user).create({
                'name': 'No permitido', 'codigo_escenario': 2, 'tipo_frase': 4,
                'company_id': self.env.company.id,
            })
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.invoice.with_user(self.invoice_user).write({
                'fel_frase_extra_ids': [Command.create({
                    'name': 'Creación por relación no permitida',
                    'codigo_escenario': 3, 'tipo_frase': 4,
                    'company_id': self.env.company.id,
                })],
            })
        self.invoice.with_user(self.invoice_user).write({
            'fel_frase_extra_ids': [Command.clear()],
        })
        self.assertFalse(self.invoice.fel_frase_extra_ids)

    def test_manager_can_edit_archive_and_delete_unused_phrase(self):
        self.frase.with_user(self.manager).write({'codigo_escenario': 2, 'active': False})
        self.assertEqual(self.frase.codigo_escenario, 2)
        self.frase.with_user(self.manager).unlink()
        self.assertFalse(self.frase.exists())

    def test_company_isolation_and_invoice_company_check(self):
        other_frase = self.frase_model.sudo().create({
            'name': 'Frase de otra compañía', 'codigo_escenario': 1, 'tipo_frase': 4,
            'company_id': self.other_company.id,
        })
        visible = self.frase_model.with_user(self.invoice_user).with_context(
            allowed_company_ids=[self.env.company.id],
        ).search([])
        self.assertNotIn(other_frase, visible)
        with self.assertRaises(AccessError):
            other_frase.with_user(self.invoice_user).read(['name'])
        with self.assertRaises(UserError), self.cr.savepoint():
            self.invoice.sudo().write({
                'fel_frase_extra_ids': [Command.link(other_frase.id)],
            })

    def test_xml_keeps_journal_phrases_and_skips_duplicate_pair(self):
        duplicate = self.frase_model.create({
            'name': 'Ya configurada en el diario',
            'codigo_escenario': 1, 'tipo_frase': 1,
            'company_id': self.env.company.id,
        })
        self.invoice.fel_frase_extra_ids = duplicate | self.frase
        emision = etree.Element(DTE_NS + 'DatosEmision')
        frases = etree.SubElement(emision, DTE_NS + 'Frases')
        for tipo in ('1', '2'):
            etree.SubElement(frases, DTE_NS + 'Frase', CodigoEscenario='1', TipoFrase=tipo)
        self.invoice._fel_agregar_frases_adicionales(emision, DTE_NS)
        self.invoice._fel_agregar_frases_adicionales(emision, DTE_NS)
        self.assertEqual(len(emision.findall(DTE_NS + 'Frases')), 1)
        self.assertEqual(
            [(f.get('CodigoEscenario'), f.get('TipoFrase')) for f in frases],
            [('1', '1'), ('1', '2'), ('1', '4')],
        )

    def test_xml_without_base_phrases_and_empty_selection(self):
        emision = etree.Element(DTE_NS + 'DatosEmision')
        self.invoice._fel_agregar_frases_adicionales(emision, DTE_NS)
        self.assertEqual(len(emision), 0)
        self.invoice.fel_frase_extra_ids = self.frase
        self.invoice._fel_agregar_frases_adicionales(emision, DTE_NS)
        self.assertEqual(
            emision.find(DTE_NS + 'Frases/' + DTE_NS + 'Frase').attrib,
            {'CodigoEscenario': '1', 'TipoFrase': '4'},
        )

    def test_posted_or_certified_invoice_cannot_change_selection(self):
        self.invoice.fel_frase_extra_ids = self.frase
        # A non-FEL journal keeps this test entirely offline.
        self.invoice.journal_id.fel_tipo_dte = False
        self.invoice.action_post()
        with self.assertRaises(UserError):
            self.invoice.write({'fel_frase_extra_ids': [Command.clear()]})
        draft = self.invoice.copy({'fel_numero_autorizacion': False})
        draft.fel_numero_autorizacion = 'CERTIFICADO-DE-PRUEBA'
        with self.assertRaises(UserError):
            draft.write({'fel_frase_extra_ids': [Command.clear()]})

    def test_used_phrase_can_be_archived_but_not_redefined_or_deleted(self):
        self.invoice.fel_frase_extra_ids = self.frase
        with self.assertRaises(UserError):
            self.frase.write({'codigo_escenario': 2})
        with self.assertRaises(UserError):
            self.frase.unlink()
        self.frase.write({'active': False})
        emision = etree.Element(DTE_NS + 'DatosEmision')
        self.invoice._fel_agregar_frases_adicionales(emision, DTE_NS)
        self.assertEqual(
            emision.find(DTE_NS + 'Frases/' + DTE_NS + 'Frase').get('TipoFrase'), '4',
        )
