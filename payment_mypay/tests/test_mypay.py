# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from werkzeug.exceptions import Forbidden

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_mypay import const
from odoo.addons.payment_mypay.controllers.main import MyPayController
from odoo.addons.payment_mypay.models.payment_provider import PaymentProvider
from odoo.addons.payment_mypay.tests.common import MyPayCommon


@tagged('post_install', '-at_install')
class TestMyPay(MyPayCommon, PaymentHttpCommon):

    def test_no_item_missing_from_rendering_values(self):
        """ Test that rendering values contain the hosted payment URL. """
        tx = self._create_transaction('redirect')
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ), patch.object(
            PaymentProvider, '_mypay_create_payment', return_value=self.payment_create_response
        ):
            rendering_values = tx._get_specific_rendering_values(None)
        self.assertEqual(rendering_values, {'api_url': self.payment_url})
        self.assertEqual(tx.provider_reference, self.payment_token)

    @mute_logger('odoo.addons.payment.models.payment_transaction')
    def test_no_input_missing_from_redirect_form(self):
        """ Test that the redirect form posts to the MyPay payment URL. """
        tx = self._create_transaction('redirect')
        with patch(
            'odoo.addons.payment_mypay.models.payment_transaction.PaymentTransaction'
            '._get_specific_rendering_values',
            return_value={'api_url': self.payment_url},
        ):
            processing_values = tx._get_processing_values()
        form_info = self._extract_values_from_html_form(processing_values['redirect_form_html'])
        self.assertEqual(form_info['action'], self.payment_url)
        self.assertEqual(form_info['method'], 'get')

    def test_payment_request_payload_contains_transaction_values(self):
        """ Test that the payment/create payload matches the transaction. """
        tx = self._create_transaction('redirect')
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ):
            payload = tx._mypay_prepare_payment_request_payload()

        self.assertEqual(payload['custom'], tx.reference)
        self.assertEqual(payload['currency'], tx.currency_id.name)
        self.assertEqual(payload['full_name'], tx.partner_name)
        self.assertEqual(payload['email'], tx.partner_email)
        self.assertNotIn('phone', payload)
        self.assertNotIn('payment_gateway', payload)
        self.assertTrue(payload['return_url'].startswith(self._build_url(const.RETURN_URL)))
        self.assertTrue(payload['cancel_url'].startswith(self._build_url(const.CANCEL_URL)))
        return_query = parse_qs(urlparse(payload['return_url']).query)
        self.assertIn('reference', return_query)
        self.assertIn('access_token', return_query)
        self.assertNotIn('token', return_query)

    def test_payment_request_payload_includes_selected_gateway(self):
        """ Test that a gateway payment method is sent as payment_gateway. """
        method = self.env.ref('payment_mypay.payment_method_moamalat')
        method.active = True
        tx = self._create_transaction('redirect', payment_method_id=method.id)
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ):
            payload = tx._mypay_prepare_payment_request_payload()
        self.assertEqual(payload['payment_gateway'], 'moamalat')

    def test_gateway_payload_includes_libyan_phone_for_autosubmit(self):
        """ Test gateway alias + Libyan phone are both present for Auto-Submit. """
        method = self.env.ref('payment_mypay.payment_method_sahary_pay')
        method.active = True
        tx = self._create_transaction('redirect', payment_method_id=method.id)
        tx.write({'partner_phone': '0912345678'})
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ):
            payload = tx._mypay_prepare_payment_request_payload()
        self.assertEqual(payload['payment_gateway'], 'sahary-pay')
        self.assertEqual(payload['phone'], '0912345678')
        self.assertIn('full_name', payload)
        self.assertIn('email', payload)

    def test_generic_mypay_method_omits_payment_gateway(self):
        """ Test that the generic MyPay method leaves gateway selection to MyPay. """
        tx = self._create_transaction('redirect')
        self.assertEqual(tx.payment_method_code, 'mypay')
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ):
            payload = tx._mypay_prepare_payment_request_payload()
        self.assertNotIn('payment_gateway', payload)

    def test_libyan_phone_is_normalized_in_payload(self):
        """ Test that Libyan numbers are sent in 09xxxxxxxx form. """
        tx = self._create_transaction('redirect')
        tx.write({'partner_phone': '+218 91-234-5678'})
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ):
            payload = tx._mypay_prepare_payment_request_payload()
        self.assertEqual(payload['phone'], '0912345678')

    def test_foreign_phone_is_omitted_from_payload(self):
        """ Test that non-Libyan numbers are omitted instead of failing checkout. """
        self.assertIsNone(self.env['payment.transaction']._mypay_format_phone('+1 805 555 0100'))
        self.assertIsNone(self.env['payment.transaction']._mypay_format_phone('0032 12 34 56 78'))
        self.assertEqual(
            self.env['payment.transaction']._mypay_format_phone('912345678'),
            '0912345678',
        )

    def test_get_tx_from_notification_data_returns_tx(self):
        """ Test that the transaction is found from webhook custom/reference data. """
        tx = self._create_transaction('redirect')
        tx_found = self.env['payment.transaction']._get_tx_from_notification_data(
            'mypay', self.webhook_notification_data
        )
        self.assertEqual(tx, tx_found)

    def test_processing_notification_data_confirms_transaction(self):
        """ Test that a successful webhook marks the transaction as done. """
        tx = self._create_transaction('redirect')
        tx._process_notification_data(self.webhook_notification_data)
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.provider_reference, self.payment_token)

    def test_processing_return_data_confirms_transaction(self):
        """ Test that a successful return URL marks the transaction as done. """
        tx = self._create_transaction('redirect')
        tx._process_notification_data(self.return_notification_data)
        self.assertEqual(tx.state, 'done')

    def test_processing_cancel_data_cancels_transaction(self):
        """ Test that a cancel notification marks the transaction as canceled. """
        tx = self._create_transaction('redirect')
        tx._process_notification_data({'reference': self.reference, 'type': 'cancel'})
        self.assertEqual(tx.state, 'cancel')

    def test_webhook_amount_mismatch_raises(self):
        """ Test that a webhook with a different amount is rejected. """
        tx = self._create_transaction('redirect')
        data = dict(self.webhook_notification_data, amount=1.00)
        with self.assertRaises(ValidationError):
            tx._process_notification_data(data)
        self.assertNotEqual(tx.state, 'done')

    @mute_logger('odoo.addons.payment_mypay.controllers.main')
    def test_webhook_notification_triggers_processing(self):
        """ Test that a signed webhook triggers notification handling. """
        self._create_transaction('redirect')
        url = self._build_url(const.WEBHOOK_URL)
        with patch.object(MyPayController, '_verify_notification_signature'), patch(
            'odoo.addons.payment.models.payment_transaction.PaymentTransaction'
            '._handle_notification_data'
        ) as handle_notification_data_mock:
            self._make_json_request(url, data=self.webhook_notification_data)
        self.assertEqual(handle_notification_data_mock.call_count, 1)

    @mute_logger('odoo.addons.payment_mypay.controllers.main')
    def test_webhook_notification_triggers_signature_check(self):
        """ Test that receiving a webhook triggers a signature check. """
        self._create_transaction('redirect')
        url = self._build_url(const.WEBHOOK_URL)
        with patch.object(
            MyPayController, '_verify_notification_signature'
        ) as signature_check_mock:
            self._make_json_request(url, data=self.webhook_notification_data)
        self.assertEqual(signature_check_mock.call_count, 1)

    def test_accept_webhook_notification_with_valid_signature(self):
        """ Test HMAC verification of a valid webhook signature. """
        tx = self._create_transaction('redirect')
        raw_body = json.dumps(self.webhook_notification_data).encode()
        signature = hmac.new(
            self.provider.mypay_webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        self._assert_does_not_raise(
            Forbidden,
            MyPayController._verify_notification_signature,
            raw_body,
            signature,
            tx,
        )

    @mute_logger('odoo.addons.payment_mypay.controllers.main')
    def test_reject_notification_with_missing_signature(self):
        """ Test that a missing webhook signature is rejected. """
        tx = self._create_transaction('redirect')
        self.assertRaises(
            Forbidden,
            MyPayController._verify_notification_signature,
            b'{}',
            None,
            tx,
        )

    @mute_logger('odoo.addons.payment_mypay.controllers.main')
    def test_reject_notification_with_invalid_signature(self):
        """ Test that an invalid webhook signature is rejected. """
        tx = self._create_transaction('redirect')
        self.assertRaises(
            Forbidden,
            MyPayController._verify_notification_signature,
            b'{}',
            'invalid',
            tx,
        )

    def test_return_url_confirms_via_status_enquiry(self):
        """ Test that return confirms payment through Payment Status enquiry. """
        tx = self._create_transaction('redirect')
        tx.provider_reference = self.payment_token
        access_token = self._generate_test_access_token(tx.reference, tx.amount)
        url = self._build_url(const.RETURN_URL)
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ), patch.object(
            PaymentProvider,
            '_mypay_get_payment_status',
            return_value=self.status_success_data,
        ) as status_mock:
            self._make_http_get_request(url, params={
                'reference': tx.reference,
                'access_token': access_token,
                'type': 'success',
                'token': self.payment_token,
            })
        status_mock.assert_called()
        self.assertEqual(tx.state, 'done')

    def test_return_url_success_query_without_paid_status_stays_pending(self):
        """ Test that a success redirect does not confirm without Status success. """
        tx = self._create_transaction('redirect')
        tx.provider_reference = self.payment_token
        access_token = self._generate_test_access_token(tx.reference, tx.amount)
        url = self._build_url(const.RETURN_URL)
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ), patch.object(
            PaymentProvider,
            '_mypay_get_payment_status',
            return_value=self.status_pending_data,
        ):
            self._make_http_get_request(url, params={
                'reference': tx.reference,
                'access_token': access_token,
                'type': 'success',
                'token': self.payment_token,
            })
        self.assertEqual(tx.state, 'draft')

    def test_cancel_url_leaves_open_when_status_still_pending(self):
        """ Test that cancel does not cancel while MyPay status is still pending. """
        tx = self._create_transaction('redirect')
        tx.provider_reference = self.payment_token
        access_token = self._generate_test_access_token(tx.reference, tx.amount)
        url = self._build_url(const.CANCEL_URL)
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ), patch.object(
            PaymentProvider,
            '_mypay_get_payment_status',
            return_value=self.status_pending_data,
        ):
            self._make_http_get_request(url, params={
                'reference': tx.reference,
                'access_token': access_token,
                'type': 'cancel',
            })
        self.assertEqual(tx.state, 'draft')

    def test_cancel_url_cancels_when_status_cancelled(self):
        """ Test that cancel marks canceled when Status reports cancelled. """
        tx = self._create_transaction('redirect')
        tx.provider_reference = self.payment_token
        access_token = self._generate_test_access_token(tx.reference, tx.amount)
        url = self._build_url(const.CANCEL_URL)
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ), patch.object(
            PaymentProvider,
            '_mypay_get_payment_status',
            return_value=self.status_cancelled_data,
        ):
            self._make_http_get_request(url, params={
                'reference': tx.reference,
                'access_token': access_token,
                'type': 'cancel',
            })
        self.assertEqual(tx.state, 'cancel')

    def test_cancel_url_confirms_when_status_already_paid(self):
        """ Test that cancel still confirms when Status reports success. """
        tx = self._create_transaction('redirect')
        tx.provider_reference = self.payment_token
        access_token = self._generate_test_access_token(tx.reference, tx.amount)
        url = self._build_url(const.CANCEL_URL)
        with patch(
            'odoo.addons.payment.utils.generate_access_token',
            new=self._generate_test_access_token,
        ), patch.object(
            PaymentProvider,
            '_mypay_get_payment_status',
            return_value=self.status_success_data,
        ):
            self._make_http_get_request(url, params={
                'reference': tx.reference,
                'access_token': access_token,
                'type': 'cancel',
            })
        self.assertEqual(tx.state, 'done')

    @mute_logger('odoo.addons.payment_mypay.controllers.main')
    def test_return_url_with_invalid_token_does_not_confirm(self):
        """ Test that a forged return URL does not confirm the transaction. """
        tx = self._create_transaction('redirect')
        url = self._build_url(const.RETURN_URL)
        with patch.object(PaymentProvider, '_mypay_get_payment_status') as status_mock:
            self._make_http_get_request(url, params={
                'reference': tx.reference,
                'access_token': 'forged',
                'type': 'success',
            })
        status_mock.assert_not_called()
        self.assertEqual(tx.state, 'draft')

    def test_status_enquiry_marks_transaction_done(self):
        """ Test that a successful status enquiry marks the transaction done. """
        tx = self._create_transaction('redirect')
        tx.provider_reference = self.payment_token
        with patch.object(
            PaymentProvider,
            '_mypay_get_payment_status',
            return_value=self.status_success_data,
        ):
            tx._mypay_enquire_and_process()
        self.assertEqual(tx.state, 'done')

    def test_status_enquiry_amount_mismatch_raises(self):
        """ Test that a status amount mismatch is rejected. """
        tx = self._create_transaction('redirect')
        tx.provider_reference = self.payment_token
        data = dict(self.status_success_data, amount=1.00)
        with patch.object(PaymentProvider, '_mypay_get_payment_status', return_value=data):
            with self.assertRaises(ValidationError):
                tx._mypay_enquire_and_process()
        self.assertNotEqual(tx.state, 'done')

    def test_status_enquiry_uses_basic_auth_get(self):
        """ Test that status enquiry calls GET with Basic Auth headers. """
        captured = {}
        success_data = self.status_success_data

        def fake_get(url, params=None, headers=None, timeout=None, verify=None):
            captured['url'] = url
            captured['params'] = params
            captured['headers'] = headers

            class _Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {'data': success_data}

            return _Response()

        with patch('odoo.addons.payment_mypay.models.payment_provider.requests.get', new=fake_get):
            data = self.provider._mypay_get_payment_status(
                token=self.payment_token, custom=self.reference
            )
        self.assertEqual(data['status'], 'success')
        self.assertIn('/payment/status', captured['url'])
        self.assertEqual(captured['params']['token'], self.payment_token)
        self.assertTrue(captured['headers']['Authorization'].startswith('Basic '))

    def test_enabled_state_allows_http_without_webhook_secret(self):
        """ Test that Enabled works without public HTTPS or webhook secret. """
        self.env['ir.config_parameter'].sudo().set_param(
            'web.base.url', 'http://localhost:8069'
        )
        self.provider.mypay_webhook_secret = False
        self.provider.state = 'enabled'
        self.assertEqual(self.provider.state, 'enabled')
        self.provider.invalidate_recordset([
            'mypay_webhook_is_https',
            'mypay_webhook_reachability_warning',
        ])
        self.assertFalse(self.provider.mypay_webhook_is_https)
        self.assertTrue(self.provider.mypay_webhook_reachability_warning)

    def test_test_state_allows_http_with_reachability_warning(self):
        """ Test that Test mode stays allowed on HTTP but shows a warning. """
        self.env['ir.config_parameter'].sudo().set_param(
            'web.base.url', 'http://localhost:8069'
        )
        self.provider.state = 'test'
        self.provider.invalidate_recordset([
            'mypay_webhook_url',
            'mypay_webhook_is_https',
            'mypay_webhook_reachability_warning',
        ])
        self.assertEqual(self.provider.state, 'test')
        self.assertFalse(self.provider.mypay_webhook_is_https)
        self.assertTrue(self.provider.mypay_webhook_reachability_warning)

    def test_cron_revives_recent_cancel_when_status_success(self):
        """ Test that cron can move a recent cancel to done after late success. """
        tx = self._create_transaction('redirect')
        tx.provider_reference = self.payment_token
        tx._set_canceled()
        self.assertEqual(tx.state, 'cancel')
        with patch.object(
            PaymentProvider,
            '_mypay_get_payment_status',
            return_value=self.status_success_data,
        ):
            self.env['payment.transaction']._cron_mypay_sync_pending_transactions()
        self.assertEqual(tx.state, 'done')

    def test_webhook_currency_mismatch_raises(self):
        """ Test that a webhook with a different currency is rejected. """
        tx = self._create_transaction('redirect')
        data = dict(self.webhook_notification_data, currency='USD')
        with self.assertRaises(ValidationError):
            tx._process_notification_data(data)
        self.assertNotEqual(tx.state, 'done')

    def test_status_enquiry_409_raises_clear_error(self):
        """ Test that HTTP 409 from status enquiry raises a clear ValidationError. """
        import requests as requests_mod

        class _Response:
            status_code = 409
            text = 'conflict'

            def json(self):
                return {'message': {'error': ['Multiple payments match custom']}}

        def fake_get(*args, **kwargs):
            error = requests_mod.exceptions.HTTPError('409 Conflict')
            error.response = _Response()
            raise error

        with patch(
            'odoo.addons.payment_mypay.models.payment_provider.requests.get',
            new=fake_get,
        ):
            with self.assertRaises(ValidationError) as catch:
                self.provider._mypay_get_payment_status(custom=self.reference)
        # Message may be translated (e.g. ar_001) depending on the test database language.
        self.assertRegex(
            str(catch.exception),
            r'Multiple payments match this custom reference|عدة مدفوعات تطابق هذا المرجع المخصص',
        )
