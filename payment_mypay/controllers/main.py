# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
import logging
import pprint

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_mypay import const

_logger = logging.getLogger(__name__)


class MyPayController(http.Controller):

    @http.route(const.RETURN_URL, type='http', auth='public', methods=['GET'], csrf=False)
    def mypay_return(self, **data):
        """ Process the browser return from MyPay hosted checkout.

        Payment Status enquiry is the source of truth; the query ``type`` alone is not.

        :param dict data: The query string parameters.
        """
        _logger.info("handling redirection from MyPay with data:\n%s", pprint.pformat(data))
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'mypay', data
            )
            self._verify_return_access_token(data, tx_sudo)
            payment_token = data.get('token') or data.get('transaction_id')
            if payment_token:
                tx_sudo.provider_reference = payment_token
            tx_sudo._mypay_enquire_and_process(pending_behavior='ignore')
        except ValidationError:
            _logger.exception("Unable to handle MyPay return data; redirecting to the status page.")
        except Forbidden:
            _logger.warning("Rejected MyPay return with invalid access token.")
        return request.redirect('/payment/status')

    @http.route(const.CANCEL_URL, type='http', auth='public', methods=['GET'], csrf=False)
    def mypay_cancel(self, **data):
        """ Process the browser cancel redirect from MyPay hosted checkout.

        Payment Status decides the outcome:
        - success → Done (paid then closed the page)
        - cancelled / failed / expired → Cancel
        - created / pending → leave open for cron (avoid Cancel→Success races)
        Enquiry failure after a valid access token falls back to Cancel.

        :param dict data: The query string parameters.
        """
        _logger.info("handling cancellation from MyPay with data:\n%s", pprint.pformat(data))
        tx_sudo = None
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'mypay', data
            )
            self._verify_return_access_token(data, tx_sudo)
            payment_token = data.get('token') or data.get('transaction_id')
            if payment_token:
                tx_sudo.provider_reference = payment_token
            tx_sudo._mypay_enquire_and_process(pending_behavior='ignore')
        except ValidationError:
            _logger.exception("Unable to handle MyPay cancel data; redirecting to the status page.")
            if tx_sudo and tx_sudo.state not in ('done', 'cancel', 'error'):
                tx_sudo._set_canceled()
        except Forbidden:
            _logger.warning("Rejected MyPay cancel with invalid access token.")
        return request.redirect('/payment/status')

    @http.route(const.WEBHOOK_URL, type='http', auth='public', methods=['POST'], csrf=False)
    def mypay_webhook(self):
        """ Process the payment.success webhook sent by MyPay.

        :return: JSON acknowledgement so MyPay stops retrying.
        """
        raw_body = request.httprequest.get_data()
        signature = request.httprequest.headers.get('X-MyPay-Signature')
        try:
            data = json.loads(raw_body or b'{}')
        except json.JSONDecodeError:
            _logger.warning("Received MyPay webhook with invalid JSON.")
            raise Forbidden()

        _logger.info("Notification received from MyPay with data:\n%s", pprint.pformat(data))
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'mypay', data
            )
            self._verify_notification_signature(raw_body, signature, tx_sudo)
            tx_sudo._handle_notification_data('mypay', data)
        except ValidationError:  # Acknowledge to avoid retry storms on unrecoverable data.
            _logger.exception("Unable to handle MyPay webhook data; skipping to acknowledge.")
        return request.make_json_response({'status': 'ok'})

    @staticmethod
    def _verify_return_access_token(notification_data, tx_sudo):
        """ Check that the return URL access token matches the transaction.

        :param dict notification_data: The query string parameters.
        :param payment.transaction tx_sudo: The sudoed transaction.
        :return: None
        :raise Forbidden: If the access token is invalid.
        """
        access_token = notification_data.get('access_token')
        if not payment_utils.check_access_token(access_token, tx_sudo.reference, tx_sudo.amount):
            _logger.warning("Received MyPay return with invalid access token.")
            raise Forbidden()

    @staticmethod
    def _verify_notification_signature(raw_body, received_signature, tx_sudo):
        """ Check that the webhook HMAC-SHA256 signature is valid.

        :param bytes|str raw_body: The raw request body that was signed.
        :param str received_signature: The value of the X-MyPay-Signature header.
        :param payment.transaction tx_sudo: The sudoed transaction referenced by the payload.
        :return: None
        :raise Forbidden: If the signature is missing or invalid.
        """
        if not received_signature:
            _logger.warning("Received MyPay notification with missing signature.")
            raise Forbidden()

        secret = tx_sudo.provider_id.mypay_webhook_secret
        if not secret:
            _logger.warning("MyPay webhook secret is not configured.")
            raise Forbidden()

        if isinstance(raw_body, str):
            raw_body = raw_body.encode('utf-8')
        expected_signature = hmac.new(
            secret.encode('utf-8'), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(received_signature, expected_signature):
            _logger.warning("Received MyPay notification with invalid signature.")
            raise Forbidden()
