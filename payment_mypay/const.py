# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

PLUGIN_NAME = 'mypay-odoo'
PLUGIN_VERSION = '1.4.0'

API_URLS = {
    'enabled': 'https://mypay.ly/pay/api/v1',
    'test': 'https://mypay.ly/pay/sandbox/api/v1',
}

RETURN_URL = '/payment/mypay/return'
CANCEL_URL = '/payment/mypay/cancel'
WEBHOOK_URL = '/payment/mypay/webhook'
STATUS_ENDPOINT = 'payment/status'

# Currencies supported by the MyPay API, in ISO 4217 format.
SUPPORTED_CURRENCIES = [
    'LYD',
]

# MyPay hosted gateway aliases accepted by payment/create as payment_gateway.
PAYMENT_GATEWAY_CODES = frozenset({
    'moamalat',
    'masrafi-pay',
    'yasr-pay',
    'sahary-pay',
    'edfali',
    'sadad',
    'mobicash',
    'prepaid-card',
})

# The codes of the payment methods to activate when MyPay is activated.
# prepaid-card stays inactive until the merchant enables it on their MyPay account.
DEFAULT_PAYMENT_METHOD_CODES = {
    'mypay',
    'moamalat',
    'masrafi-pay',
    'yasr-pay',
    'sahary-pay',
    'edfali',
    'sadad',
    'mobicash',
}

# Filenames under static/src/img/ for each payment.method code.
PAYMENT_METHOD_IMAGE_FILES = {
    'mypay': 'mypay.png',
    'moamalat': 'moamalat.png',
    'masrafi-pay': 'masrafi_pay.png',
    'yasr-pay': 'yasr_pay.png',
    'sahary-pay': 'sahary_pay.png',
    'edfali': 'edfali.png',
    'sadad': 'sadad.png',
    'mobicash': 'mobicash.png',
    'prepaid-card': 'moamalat.png',
}

# Mapping of transaction states to MyPay payment statuses / events.
PAYMENT_STATUS_MAPPING = {
    'done': ('success', 'payment.success'),
    'cancel': ('cancel', 'canceled', 'cancelled', 'failed', 'expired'),
    'pending': ('created', 'pending'),
}

# Pending MyPay transactions older than this are ignored by the sync cron.
STATUS_SYNC_MAX_AGE_HOURS = 48
# Recently canceled txs are re-checked so a late success can revive them.
STATUS_SYNC_CANCEL_REVIVAL_HOURS = 6
STATUS_SYNC_BATCH_LIMIT = 100
