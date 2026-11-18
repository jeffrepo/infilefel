# -*- coding: utf-8 -*-


{
    'name': 'INFILE FEL',
    'version': '17.0.1.1.0',
    'category': 'Hidden',
    'sequence': 6,
    'summary': 'Módulo para facturacion en linea INFILE',
    'description': """

""",
    'depends': ['base','account','account_reports'],
    'data': [
        'security/ir.model.access.csv',
        'security/infilefel_frase_extra_security.xml',
        'views/infilefel_frase_extra_views.xml',
        'views/account_view.xml',
        #'views/res_company_views.xml',
        'views/account_move_views.xml',
        #'views/report_invoice.xml',
        #'views/res_partner_view.xml',
        #'views/report_invoice.xml',
        'views/reporte_ticket.xml',
        'data/paperformat_ticket.xml',
        'views/report.xml',
    ],
    'installable': True,
    'auto_install': False,
}
