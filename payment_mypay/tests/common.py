# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

from odoo.addons.payment.tests.common import PaymentCommon


class MyPayCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.mypay = cls._prepare_provider('mypay', update_values={
            'mypay_client_id': 'test_client_id',
            'mypay_secret_id': 'test_secret_id',
            'mypay_webhook_secret': 'test_webhook_secret',
        })
        cls.provider = cls.mypay
        cls.payment_method = cls.env.ref('payment_mypay.payment_method_mypay')
        cls.payment_method.active = True
        cls.payment_method_id = cls.payment_method.id
        cls.payment_method_code = cls.payment_method.code
        cls.currency_lyd = cls._prepare_currency('LYD')
        cls.currency = cls.currency_lyd

        cls.payment_token = 'ABC123XYZ789'
        cls.payment_url = f'https://mypay.ly/pay/sandbox/v1/user/payment/preview/{cls.payment_token}'
        cls.payment_create_response = {
            'token': cls.payment_token,
            'payment_url': cls.payment_url,
        }
        cls.webhook_notification_data = {
            'event': 'payment.success',
            'type': 'QR_PAY',
            'transaction_id': cls.payment_token,
            'token': cls.payment_token,
            'trx_ref': 'REF_456789',
            'status': 'success',
            'gateway': 'MOAMALAT',
            'custom': cls.reference,
            'amount': cls.amount,
            'currency': 'LYD',
            'timestamp': '2024-01-12 14:30:00',
        }
        cls.return_notification_data = {
            'reference': cls.reference,
            'type': 'success',
            'token': cls.payment_token,
        }
        cls.status_success_data = {
            'status': 'success',
            'token': cls.payment_token,
            'custom': cls.reference,
            'amount': cls.amount,
            'currency': 'LYD',
            'gateway': 'moamalat',
            'transaction_id': cls.payment_token,
            'trx_ref': cls.payment_token,
            'environment': 'SANDBOX',
            'updated_at': '2024-01-12 14:30:00',
        }
        cls.status_pending_data = {
            **cls.status_success_data,
            'status': 'pending',
        }
        cls.status_cancelled_data = {
            **cls.status_success_data,
            'status': 'cancelled',
        }
