{
    'name': 'Waitress Cash Control',
    'version': '17.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Manager-only order deletion/cancellation with mandatory audit, '
               'extended Daily Sales report, and an 80mm thermal end-of-session report',
    'author': 'Custom Development',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/res_users_views.xml',
        'wizard/pos_order_deletion_wizard_views.xml',
        'views/pos_order_views.xml',
        'views/pos_order_deletion_audit_views.xml',
        'views/pos_session_views.xml',
        'report/report_saledetails_summary.xml',
        'report/thermal_session_report_actions.xml',
        'report/thermal_session_report_templates.xml',
    ],
    # Confirmed against this install's actual
    # addons/point_of_sale/__manifest__.py — 'point_of_sale._assets_pos'
    # is the real bundle key on this instance, not just the general
    # convention.
    'assets': {
        'point_of_sale._assets_pos': [
            'waitress_cash_control/static/src/app/session_receipt/session_receipt.js',
            'waitress_cash_control/static/src/app/session_receipt/session_receipt.xml',
            'waitress_cash_control/static/src/app/navbar/closing_popup/closing_popup_patch.js',
            'waitress_cash_control/static/src/app/screens/ticket_screen/ticket_screen_patch.js',
            'waitress_cash_control/static/src/app/screens/product_screen/product_screen_patch.js',
        ],
    },
    'installable': True,
    'application': False,
}
