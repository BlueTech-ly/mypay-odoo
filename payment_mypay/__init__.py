# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

from . import controllers
from . import models
from . import wizard

from odoo.addons.payment import setup_provider, reset_payment_provider


def post_init_hook(env):
    setup_provider(env, 'mypay')
    env['payment.provider']._mypay_sync_gateway_payment_methods()


def uninstall_hook(env):
    reset_payment_provider(env, 'mypay')
