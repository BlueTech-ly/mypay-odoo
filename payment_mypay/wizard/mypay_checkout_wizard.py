# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from odoo.addons.payment_mypay import const
from odoo.addons.payment_mypay.models.payment_transaction import PaymentTransaction


class MyPayCheckoutWizard(models.TransientModel):
    _name = 'mypay.checkout.wizard'
    _description = "Pay invoice via MyPay gateway"

    move_id = fields.Many2one(
        comodel_name='account.move',
        string="Invoice",
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='move_id.partner_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='move_id.currency_id',
        readonly=True,
    )
    amount = fields.Monetary(
        string="Amount",
        currency_field='currency_id',
        required=True,
    )
    payment_method_id = fields.Many2one(
        comodel_name='payment.method',
        string="Payment Gateway",
        required=True,
        domain="[('id', 'in', available_payment_method_ids)]",
    )
    available_payment_method_ids = fields.Many2many(
        comodel_name='payment.method',
        compute='_compute_available_payment_method_ids',
    )
    phone = fields.Char(
        string="Customer Phone",
        required=True,
        help="Libyan mobile number required by MyPay Auto-Submit "
             "(e.g. 0912345678). Without it, MyPay shows all gateways.",
    )

    @api.depends('move_id')
    def _compute_available_payment_method_ids(self):
        methods = self.env['payment.method'].sudo().search([
            ('code', 'in', list(const.PAYMENT_GATEWAY_CODES)),
            ('active', '=', True),
            ('provider_ids.code', '=', 'mypay'),
        ])
        for wizard in self:
            wizard.available_payment_method_ids = methods

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        move = self.env['account.move'].browse(self.env.context.get('active_id'))
        if move:
            values['move_id'] = move.id
            link_values = move._get_default_payment_link_values()
            values['amount'] = link_values.get('amount') or move.amount_residual
            partner = move.partner_id
            phone = PaymentTransaction._mypay_format_phone(
                partner.mobile or partner.phone
            )
            if phone:
                values['phone'] = phone
        return values

    def action_open_mypay(self):
        """ Create a MyPay transaction with the selected gateway alias and redirect. """
        self.ensure_one()
        move = self.move_id
        if not move.mypay_can_pay:
            raise UserError(_(
                "MyPay checkout is only available for posted customer invoices with a residual"
                " amount, when the MyPay provider is enabled or in test mode."
            ))

        phone = PaymentTransaction._mypay_format_phone(self.phone)
        if not phone:
            raise UserError(_(
                "Enter a valid Libyan mobile number (09xxxxxxxx). MyPay needs it with the"
                " gateway alias to skip the gateway selection page."
            ))

        if self.payment_method_id.code not in const.PAYMENT_GATEWAY_CODES:
            raise UserError(_("Select a MyPay gateway (moamalat, edfali, …)."))

        if self.amount <= 0 or self.amount > move.amount_residual:
            raise UserError(_(
                "Amount must be positive and not greater than the invoice residual."
            ))

        provider = self.env['payment.provider'].sudo().search([
            ('code', '=', 'mypay'),
            ('state', 'in', ('enabled', 'test')),
            ('company_id', '=', move.company_id.id),
        ], limit=1)
        if not provider:
            raise UserError(_("No MyPay provider is enabled for this company."))

        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': self.payment_method_id.id,
            'amount': self.amount,
            'currency_id': move.currency_id.id,
            'partner_id': move.partner_id.id,
            'partner_name': move.partner_id.name,
            'partner_email': move.partner_id.email,
            'partner_phone': phone,
            'invoice_ids': [Command.set(move.ids)],
        })
        rendering_values = tx._get_specific_rendering_values(None)
        payment_url = rendering_values.get('api_url')
        if not payment_url:
            raise UserError(_("MyPay did not return a payment URL."))
        return {
            'type': 'ir.actions.act_url',
            'url': payment_url,
            'target': 'new',
        }
