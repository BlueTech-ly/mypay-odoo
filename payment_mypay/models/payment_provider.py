# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

import base64
import logging
import pprint

import requests
from werkzeug import urls

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.release import version as odoo_version
from odoo.tools.misc import file_path

from odoo.addons.payment_mypay import const

_logger = logging.getLogger(__name__)

_LOCAL_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('mypay', "MyPay")], ondelete={'mypay': 'set default'}
    )
    mypay_client_id = fields.Char(
        string="Client ID",
        help="The Client ID provided in the MyPay merchant dashboard.",
        required_if_provider='mypay',
        groups='base.group_system',
    )
    mypay_secret_id = fields.Char(
        string="Secret ID",
        help="The Secret ID provided in the MyPay merchant dashboard.",
        required_if_provider='mypay',
        groups='base.group_system',
    )
    mypay_webhook_secret = fields.Char(
        string="Webhook Secret",
        help="Optional. Used to verify X-MyPay-Signature on incoming webhooks. "
             "Payment confirmation still works via Payment Status enquiry without "
             "a public HTTPS webhook endpoint.",
        groups='base.group_system',
    )
    mypay_webhook_url = fields.Char(
        string="Webhook URL",
        compute='_compute_mypay_webhook_fields',
        help="Optional. Paste this URL in the MyPay merchant dashboard under API "
             "Credentials → Webhook when a public HTTPS URL is available.",
    )
    mypay_webhook_is_https = fields.Boolean(
        string="Webhook URL uses HTTPS",
        compute='_compute_mypay_webhook_fields',
    )
    mypay_webhook_reachability_warning = fields.Char(
        string="Webhook Reachability Warning",
        compute='_compute_mypay_webhook_fields',
    )

    # === COMPUTE METHODS === #

    def _compute_feature_support_fields(self):
        """ Override of `payment` to disable unsupported MyPay features. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'mypay').update({
            'support_refund': 'none',
            'support_tokenization': False,
            'support_express_checkout': False,
        })

    @api.depends('code')
    def _compute_mypay_webhook_fields(self):
        for provider in self:
            if provider.code != 'mypay':
                provider.mypay_webhook_url = False
                provider.mypay_webhook_is_https = False
                provider.mypay_webhook_reachability_warning = False
                continue
            base_url = provider.get_base_url() or ''
            provider.mypay_webhook_url = urls.url_join(base_url, const.WEBHOOK_URL)
            provider.mypay_webhook_is_https = provider._mypay_base_url_is_https(base_url)
            provider.mypay_webhook_reachability_warning = (
                provider._mypay_get_webhook_reachability_warning(base_url)
            )

    # === BUSINESS METHODS - WEBHOOK REACHABILITY === #

    @staticmethod
    def _mypay_base_url_is_https(base_url):
        """ Return whether the Odoo base URL uses HTTPS.

        :param str base_url: The value of web.base.url.
        :rtype: bool
        """
        return (urls.url_parse(base_url or '').scheme or '').lower() == 'https'

    @staticmethod
    def _mypay_base_url_is_local(base_url):
        """ Return whether the Odoo base URL points at a local-only host.

        :param str base_url: The value of web.base.url.
        :rtype: bool
        """
        host = (urls.url_parse(base_url or '').host or '').lower()
        return host in _LOCAL_HOSTS or host.endswith('.local')

    def _mypay_get_webhook_reachability_warning(self, base_url=None):
        """ Return a warning when inbound webhooks are unlikely to arrive.

        Payment Status enquiry still confirms payments without a public HTTPS URL.

        :param str|None base_url: Optional base URL override.
        :return: Warning text, or False when the URL looks reachable for webhooks.
        :rtype: str|bool
        """
        self.ensure_one()
        base_url = base_url if base_url is not None else (self.get_base_url() or '')
        if not self._mypay_base_url_is_https(base_url):
            return _(
                "Inbound MyPay webhooks need a public HTTPS web.base.url. Payments can "
                "still be confirmed via Payment Status enquiry and the return URL. "
                "Optional: use a reverse proxy or tunnel, then update "
                "Settings → System Parameters → web.base.url."
            )
        if self._mypay_base_url_is_local(base_url):
            return _(
                "MyPay cannot reach localhost for webhooks. Payments can still be "
                "confirmed via Payment Status enquiry. Optional: expose Odoo with a "
                "public HTTPS URL (Cloudflare Tunnel or reverse proxy)."
            )
        return False

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_supported_currencies(self):
        """ Override of `payment` to return the supported currencies. """
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'mypay':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    def _get_default_payment_method_codes(self):
        """ Override of `payment` to return the default payment method codes. """
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'mypay':
            return default_codes
        return const.DEFAULT_PAYMENT_METHOD_CODES

    @api.model
    def _mypay_sync_gateway_payment_methods(self):
        """ Link MyPay gateway methods to the provider and activate defaults.

        Called on module install/upgrade so existing databases pick up new gateway
        payment methods without manually re-enabling the provider.
        """
        method_codes = const.DEFAULT_PAYMENT_METHOD_CODES | const.PAYMENT_GATEWAY_CODES
        methods = self.env['payment.method'].with_context(active_test=False).search([
            ('code', 'in', list(method_codes)),
        ])
        providers = self.with_context(active_test=False).search([('code', '=', 'mypay')])
        for provider in providers:
            provider.payment_method_ids = [(4, method.id) for method in methods]
            if provider.state in ('enabled', 'test'):
                provider._activate_default_pms()
        self._mypay_sync_payment_method_images()

    @api.model
    def _mypay_sync_payment_method_images(self):
        """ Force-refresh payment method logos from module image files.

        XML ``type="base64" file=...`` updates are not always applied to existing
        ``fields.Image`` values on upgrade, so logos are written explicitly.
        """
        methods = self.env['payment.method'].with_context(active_test=False)
        for code, filename in const.PAYMENT_METHOD_IMAGE_FILES.items():
            method = methods.search([('code', '=', code)], limit=1)
            if not method:
                continue
            try:
                path = file_path(f'payment_mypay/static/src/img/{filename}')
            except FileNotFoundError:
                _logger.warning("MyPay payment method image missing: %s", filename)
                continue
            with open(path, 'rb') as image_file:
                method.write({'image': base64.b64encode(image_file.read())})

    def _should_build_inline_form(self, is_validation=False):
        """ Override of `payment` to always use the redirect flow. """
        if self.code == 'mypay':
            return False
        return super()._should_build_inline_form(is_validation)

    def _mypay_get_api_url(self):
        """ Return the MyPay API base URL matching the provider state.

        :return: The API base URL without a trailing slash.
        :rtype: str
        """
        self.ensure_one()
        environment = 'enabled' if self.state == 'enabled' else 'test'
        return const.API_URLS[environment]

    def _mypay_get_request_headers(self, access_token=None, basic_auth=False):
        """ Return HTTP headers for MyPay API requests.

        :param str access_token: Optional Bearer token for authenticated endpoints.
        :param bool basic_auth: When True, use Client ID / Secret ID as Basic Auth.
        :return: The request headers.
        :rtype: dict
        """
        self.ensure_one()
        headers = {
            'Accept': 'application/json',
            'X-MyPay-Plugin': const.PLUGIN_NAME,
            'X-MyPay-Plugin-Version': const.PLUGIN_VERSION,
            'X-MyPay-Site-Identifier': self.get_base_url(),
            'X-MyPay-Odoo-Version': odoo_version,
        }
        if basic_auth:
            if not self.mypay_client_id or not self.mypay_secret_id:
                raise ValidationError(
                    "MyPay: " + _("The Client ID and Secret ID are required.")
                )
            credentials = base64.b64encode(
                f'{self.mypay_client_id}:{self.mypay_secret_id}'.encode()
            ).decode()
            headers['Authorization'] = f'Basic {credentials}'
        elif access_token:
            headers['Content-Type'] = 'application/json'
            headers['Authorization'] = f'Bearer {access_token}'
        else:
            headers['Content-Type'] = 'application/json'
        return headers

    def _mypay_make_request(self, endpoint, payload, access_token=None):
        """ Make a POST request to the MyPay API and return the JSON body.

        :param str endpoint: Endpoint path relative to the API base URL.
        :param dict payload: JSON payload.
        :param str access_token: Optional Bearer token.
        :return: The decoded JSON response.
        :rtype: dict
        :raise ValidationError: If the request fails.
        """
        self.ensure_one()
        url = f"{self._mypay_get_api_url()}/{endpoint.lstrip('/')}"
        headers = self._mypay_get_request_headers(access_token)
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=(10, 30), verify=True
            )
            response.raise_for_status()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            _logger.exception("Unable to reach MyPay endpoint at %s", url)
            raise ValidationError(
                "MyPay: " + _("Could not establish the connection to the API.")
            )
        except requests.exceptions.HTTPError as error:
            error_message = self._mypay_parse_error_message(error.response)
            _logger.exception(
                "Invalid MyPay API request at %s with data:\n%s",
                url,
                pprint.pformat(self._mypay_redact_payload(payload)),
            )
            raise ValidationError(
                "MyPay: " + _("The communication with the API failed: %s", error_message)
            ) from error
        return self._mypay_decode_json_response(response, url)

    def _mypay_make_get_request(self, endpoint, params=None):
        """ Make a GET request with Basic Auth and return the JSON body.

        :param str endpoint: Endpoint path relative to the API base URL.
        :param dict|None params: Query string parameters.
        :return: The decoded JSON response.
        :rtype: dict
        :raise ValidationError: If the request fails.
        """
        self.ensure_one()
        url = f"{self._mypay_get_api_url()}/{endpoint.lstrip('/')}"
        headers = self._mypay_get_request_headers(basic_auth=True)
        try:
            response = requests.get(
                url, params=params or {}, headers=headers, timeout=(10, 30), verify=True
            )
            response.raise_for_status()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            _logger.exception("Unable to reach MyPay endpoint at %s", url)
            raise ValidationError(
                "MyPay: " + _("Could not establish the connection to the API.")
            )
        except requests.exceptions.HTTPError as error:
            status_code = getattr(error.response, 'status_code', None)
            if status_code == 409:
                _logger.exception(
                    "MyPay status enquiry conflict at %s with params:\n%s",
                    url,
                    pprint.pformat(params or {}),
                )
                raise ValidationError(
                    "MyPay: " + _(
                        "Multiple payments match this custom reference. "
                        "Retry the status enquiry with the payment token "
                        "(provider reference)."
                    )
                ) from error
            error_message = self._mypay_parse_error_message(error.response)
            _logger.exception(
                "Invalid MyPay API request at %s with params:\n%s",
                url,
                pprint.pformat(params or {}),
            )
            raise ValidationError(
                "MyPay: " + _("The communication with the API failed: %s", error_message)
            ) from error
        return self._mypay_decode_json_response(response, url)

    def _mypay_decode_json_response(self, response, url):
        """ Decode a MyPay JSON response body.

        :param requests.Response response: The HTTP response.
        :param str url: The request URL (for logging).
        :return: The decoded JSON body.
        :rtype: dict
        :raise ValidationError: If the body is not JSON.
        """
        try:
            return response.json()
        except ValueError:
            _logger.exception("MyPay returned a non-JSON response from %s", url)
            raise ValidationError("MyPay: " + _("The API returned an invalid response."))

    def _mypay_get_access_token(self):
        """ Request a one-time access token. Do not cache or reuse it.

        :return: The access token.
        :rtype: str
        :raise ValidationError: If credentials are missing or the token is absent.
        """
        self.ensure_one()
        if not self.mypay_client_id or not self.mypay_secret_id:
            raise ValidationError(
                "MyPay: " + _("The Client ID and Secret ID are required.")
            )
        data = self._mypay_make_request('authentication/token', {
            'client_id': self.mypay_client_id,
            'secret_id': self.mypay_secret_id,
        })
        access_token = (data.get('data') or {}).get('access_token')
        if not access_token:
            raise ValidationError(
                "MyPay: " + _("Access token not found in the API response.")
            )
        return access_token

    def _mypay_create_payment(self, payload):
        """ Authenticate and create a hosted payment.

        :param dict payload: The `/payment/create` body.
        :return: The `data` object (`token`, `payment_url`).
        :rtype: dict
        :raise ValidationError: If the payment cannot be created.
        """
        self.ensure_one()
        access_token = self._mypay_get_access_token()
        response = self._mypay_make_request(
            'payment/create', payload, access_token=access_token
        )
        payment_data = response.get('data') or {}
        if not payment_data.get('payment_url') or not payment_data.get('token'):
            raise ValidationError(
                "MyPay: " + _("Payment URL or token not found in the API response.")
            )
        return payment_data

    def _mypay_get_payment_status(self, token=None, custom=None):
        """ Enquire payment status via GET /payment/status (Basic Auth).

        :param str|None token: Public payment token from payment/create.
        :param str|None custom: Merchant order / transaction reference.
        :return: The `data` object from the status response.
        :rtype: dict
        :raise ValidationError: If parameters are missing or the API fails.
        """
        self.ensure_one()
        params = {}
        if token:
            params['token'] = token
        if custom:
            params['custom'] = custom
        if not params:
            raise ValidationError(
                "MyPay: " + _("A payment token or custom reference is required for status enquiry.")
            )
        response = self._mypay_make_get_request(const.STATUS_ENDPOINT, params=params)
        status_data = response.get('data') or {}
        if not status_data.get('status'):
            raise ValidationError(
                "MyPay: " + _("Payment status not found in the API response.")
            )
        return status_data

    @staticmethod
    def _mypay_parse_error_message(response):
        """ Extract a human-readable error from a MyPay HTTP error response.

        :param requests.Response response: The error response.
        :return: The error message.
        :rtype: str
        """
        try:
            body = response.json()
        except (ValueError, AttributeError):
            return response.text if response is not None else ''
        errors = (body.get('message') or {}).get('error')
        if isinstance(errors, list) and errors:
            return ' '.join(str(item) for item in errors)
        if isinstance(errors, str) and errors:
            return errors
        return body.get('message') and str(body['message']) or (response.text or '')

    @staticmethod
    def _mypay_redact_payload(payload):
        """ Return a copy of the payload with secrets removed for logging.

        :param dict payload: The original payload.
        :return: A log-safe payload.
        :rtype: dict
        """
        if not isinstance(payload, dict):
            return payload
        redacted = dict(payload)
        if 'secret_id' in redacted:
            redacted['secret_id'] = '***'
        return redacted
