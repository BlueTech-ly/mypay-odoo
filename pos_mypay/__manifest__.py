# Part of pos_mypay. See LICENSE file for full copyright and licensing details.

{
    'name': "POS MyPay",
    'version': '18.0.1.4.1',
    'category': 'Sales/Point of Sale',
    'summary': "Pay POS orders with MyPay via QR / hosted checkout.",
    'description': " ",
    'author': "MyPay",
    'website': "https://mypay.ly",
    'depends': ['payment_mypay', 'pos_online_payment'],
    'data': [
        'data/pos_payment_method_data.xml',
    ],
    'auto_install': True,
    'installable': True,
    'license': 'LGPL-3',
}
