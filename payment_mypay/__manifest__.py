# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

{
    'name': "MyPay",
    'version': '18.0.1.4.4',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Accept payments through MyPay hosted checkout.",
    'description': " ",  # Non-empty string to avoid loading the README file.
    'author': "MyPay",
    'website': "https://mypay.ly",
    'images': [
        'static/description/banner.png',
    ],
    'depends': ['payment', 'account_payment'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_mypay_templates.xml',
        'views/payment_provider_views.xml',
        'views/account_move_views.xml',
        'wizard/mypay_checkout_wizard_views.xml',
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',
        'data/payment_provider_method_link_data.xml',
        'data/payment_mypay_icon_data.xml',
        'data/ir_cron_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
