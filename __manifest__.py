{
    'name': 'INFILE FEL Vitec',
    'version': '17.0.1.0.0',
    'summary': 'Timbrado directo con INFILE sobre los documentos FEL de Vitec',
    'category': 'Accounting/Localizations/EDI',
    'depends': ['l10n_xma_einvoice_gtm', 'changing_generate_json_l10n_gtm'],
    'external_dependencies': {'python': ['requests', 'lxml']},
    'data': ['views/vitec_views.xml'],
    'installable': True,
    'auto_install': False,
}
