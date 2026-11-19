# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

import logging
import pprint
import re
from datetime import timedelta

from werkzeug import urls

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_mypay import const

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _get_specific_rendering_values(self, processing_values):
        """ Override of `payment` to request a MyPay hosted payment URL.

        :param dict processing_values: The generic and specific processing values.
        :return: The redirect rendering values.
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'mypay':
            return res

        payload = self._mypay_prepare_payment_request_payload()
        _logger.info(
            "Sending payment create request for transaction %s:\n%s",
            self.reference,
            pprint.pformat(payload),
        )
        payment_data = self.provider_id._mypay_create_payment(payload)
        _logger.info(
            "Received payment create response for transaction %s:\n%s",
            self.reference,
            pprint.pformat({'token': payment_data.get('token'), 'payment_url': payment_data.get('payment_url')}),
        )
        self.provider_reference = payment_data['token']
        return {
            'api_url': payment_data['payment_url'],
        }

    def _mypay_prepare_payment_request_payload(self):
        """ Build the `/payment/create` payload from the transaction.

        :return: The request payload.
        :rtype: dict
        """
        base_url = self.provider_id.get_base_url()
        access_token = payment_utils.generate_access_token(self.reference, self.amount)
        callback_params = urls.url_encode({
            'reference': self.reference,
            'access_token': access_token,
        })
        payload = {
            'amount': f'{self.amount:.{self.currency_id.decimal_places}f}',
            'currency': self.currency_id.name,
            'return_url': f'{urls.url_join(base_url, const.RETURN_URL)}?{callback_params}',
            'cancel_url': f'{urls.url_join(base_url, const.CANCEL_URL)}?{callback_params}',
            'custom': self.reference,
        }
        if self.payment_method_code in const.PAYMENT_GATEWAY_CODES:
            payload['payment_gateway'] = self.payment_method_code
        if self.partner_name:
            payload['full_name'] = self.partner_name
        if self.partner_email:
            payload['email'] = self.partner_email
        phone = self._mypay_format_phone(
            self.partner_phone or (self.partner_id.mobile or self.partner_id.phone)
        )
        if phone:
            payload['phone'] = phone
        return payload

    @staticmethod
    def _mypay_format_phone(phone):
        """ Return a Libyan phone number, or None when the value cannot be used.

        MyPay only accepts Libyan mobiles (optional field). Foreign numbers such as demo
        US/EU partners must be omitted so checkout does not fail.

        Accepted after normalization: ``0912345678``, ``912345678``, ``+218912345678``.

        :param str phone: The partner phone or mobile.
        :return: A 10-digit number starting with ``09``, or None.
        :rtype: str | None
        """
        if not phone:
            return None
        digits = re.sub(r'\D', '', str(phone))
        if digits.startswith('218'):
            digits = digits[3:]
        if digits.startswith('00218'):
            digits = digits[5:]
        if len(digits) == 9 and digits.startswith('9'):
            digits = f'0{digits}'
        if re.fullmatch(r'09\d{8}', digits):
            return digits
        return None

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of `payment` to find the transaction based on MyPay data.

        :param str provider_code: The provider handling the transaction.
        :param dict notification_data: The notification data.
        :return: The transaction if found.
        :rtype: payment.transaction
        :raise ValidationError: If the data is incomplete or matches no transaction.
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'mypay' or len(tx) == 1:
            return tx

        reference = notification_data.get('reference') or notification_data.get('custom')
        payment_token = notification_data.get('token') or notification_data.get('transaction_id')

        if reference:
            tx = self.search([('reference', '=', reference), ('provider_code', '=', 'mypay')])
        if not tx and payment_token:
            tx = self.search([
                ('provider_reference', '=', payment_token),
                ('provider_code', '=', 'mypay'),
            ])
        if not tx:
            raise ValidationError(
                "MyPay: " + _("No transaction found matching reference %s.", reference or payment_token)
            )
        return tx

    def _process_notification_data(self, notification_data):
        """ Override of `payment` to process the transaction based on MyPay data.

        :param dict notification_data: The notification data.
        :return: None
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'mypay':
            return

        payment_token = notification_data.get('token') or notification_data.get('transaction_id')
        if payment_token:
            self.provider_reference = payment_token

        event = (notification_data.get('event') or '').lower()
        status = (notification_data.get('status') or notification_data.get('type') or '').lower()

        if event in const.PAYMENT_STATUS_MAPPING['done'] or status in const.PAYMENT_STATUS_MAPPING['done']:
            self._mypay_validate_notification_amount(notification_data)
            self._mypay_validate_notification_currency(notification_data)
            gateway = notification_data.get('gateway')
            state_message = _("Paid with MyPay (%s).", gateway) if gateway else None
            # A later webhook must still confirm payment if the shopper hit cancel first.
            self._set_done(state_message=state_message, extra_allowed_states=('cancel',))
        elif status in const.PAYMENT_STATUS_MAPPING['cancel'] or notification_data.get('canceled'):
            self._set_canceled()
        else:
            _logger.info(
                "ignored MyPay notification for transaction %s with data:\n%s",
                self.reference,
                pprint.pformat(notification_data),
            )

    def _mypay_validate_notification_amount(self, notification_data):
        """ Ensure the notified amount matches the transaction when present.

        :param dict notification_data: The notification data.
        :return: None
        :raise ValidationError: If the amount does not match.
        """
        notified_amount = notification_data.get('amount')
        if notified_amount in (None, ''):
            return
        try:
            notified_amount = float(notified_amount)
        except (TypeError, ValueError):
            raise ValidationError("MyPay: " + _("Received data with invalid amount."))
        if float_compare(notified_amount, self.amount, precision_rounding=self.currency_id.rounding) != 0:
            raise ValidationError(
                "MyPay: " + _(
                    "The amount of notification %(notification_amount)s does not match the "
                    "transaction amount %(tx_amount)s.",
                    notification_amount=notified_amount,
                    tx_amount=self.amount,
                )
            )

    def _mypay_validate_notification_currency(self, notification_data):
        """ Ensure the notified currency matches the transaction when present.

        :param dict notification_data: The notification / status data.
        :return: None
        :raise ValidationError: If the currency does not match.
        """
        notified_currency = notification_data.get('currency')
        if not notified_currency:
            return
        if str(notified_currency).upper() != (self.currency_id.name or '').upper():
            raise ValidationError(
                "MyPay: " + _(
                    "The currency of notification %(notification_currency)s does not match the "
                    "transaction currency %(tx_currency)s.",
                    notification_currency=notified_currency,
                    tx_currency=self.currency_id.name,
                )
            )

    def _mypay_enquire_and_process(self, pending_behavior='ignore', allow_cancel_revival=False):
        """ Confirm the transaction from MyPay Payment Status enquiry.

        :param str pending_behavior: What to do when status is created/pending:
            ``ignore`` leaves the transaction unchanged; ``cancel`` marks it canceled.
        :param bool allow_cancel_revival: When True, a canceled transaction may move
            to Done if MyPay reports ``success`` (Cancel→Success race recovery).
        :return: None
        """
        self.ensure_one()
        if self.provider_code != 'mypay' or self.state in ('done', 'error'):
            return
        if self.state == 'cancel' and not allow_cancel_revival:
            return

        status_data = self.provider_id._mypay_get_payment_status(
            token=self.provider_reference or None,
            custom=self.reference,
        )
        _logger.info(
            "Payment status enquiry for transaction %s:\n%s",
            self.reference,
            pprint.pformat(status_data),
        )

        payment_token = status_data.get('token') or status_data.get('transaction_id')
        if payment_token:
            self.provider_reference = payment_token

        status = (status_data.get('status') or '').lower()
        if status in const.PAYMENT_STATUS_MAPPING['done']:
            self._mypay_validate_notification_amount(status_data)
            self._mypay_validate_notification_currency(status_data)
            gateway = status_data.get('gateway')
            state_message = _("Paid with MyPay (%s).", gateway) if gateway else _(
                "Paid with MyPay (status enquiry)."
            )
            self._set_done(state_message=state_message, extra_allowed_states=('cancel',))
        elif status in const.PAYMENT_STATUS_MAPPING['cancel']:
            if self.state != 'cancel':
                self._set_canceled()
        elif status in const.PAYMENT_STATUS_MAPPING['pending']:
            if pending_behavior == 'cancel':
                self._set_canceled()
            else:
                _logger.info(
                    "MyPay payment %s still pending (status=%s).",
                    self.reference,
                    status,
                )
        else:
            _logger.info(
                "ignored MyPay status enquiry for transaction %s with data:\n%s",
                self.reference,
                pprint.pformat(status_data),
            )

    @api.model
    def _cron_mypay_sync_pending_transactions(self):
        """ Enquire MyPay status for recent draft/pending and revive late successes. """
        now = fields.Datetime.now()
        oldest = now - timedelta(hours=const.STATUS_SYNC_MAX_AGE_HOURS)
        cancel_oldest = now - timedelta(hours=const.STATUS_SYNC_CANCEL_REVIVAL_HOURS)

        pending_txs = self.search([
            ('provider_code', '=', 'mypay'),
            ('state', 'in', ('draft', 'pending')),
            ('create_date', '>=', oldest),
        ], limit=const.STATUS_SYNC_BATCH_LIMIT, order='create_date asc')

        remaining = const.STATUS_SYNC_BATCH_LIMIT - len(pending_txs)
        cancel_txs = self.browse()
        if remaining > 0:
            cancel_txs = self.search([
                ('provider_code', '=', 'mypay'),
                ('state', '=', 'cancel'),
                ('provider_reference', '!=', False),
                ('write_date', '>=', cancel_oldest),
            ], limit=remaining, order='write_date asc')

        for tx in pending_txs:
            try:
                tx._mypay_enquire_and_process(pending_behavior='ignore')
            except ValidationError:
                _logger.exception(
                    "MyPay status sync failed for transaction %s", tx.reference
                )

        for tx in cancel_txs:
            try:
                tx._mypay_enquire_and_process(
                    pending_behavior='ignore', allow_cancel_revival=True
                )
            except ValidationError:
                _logger.exception(
                    "MyPay cancel-revival sync failed for transaction %s", tx.reference
                )
