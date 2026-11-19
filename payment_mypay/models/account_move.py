# Part of payment_mypay. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    mypay_can_pay = fields.Boolean(
        string="Can Pay with MyPay",
        compute='_compute_mypay_can_pay',
    )

    @api.depends(
        'move_type',
        'state',
        'payment_state',
        'amount_residual',
        'currency_id',
        'company_id',
    )
    def _compute_mypay_can_pay(self):
        mypay_companies = self.env['payment.provider'].sudo().search([
            ('code', '=', 'mypay'),
            ('state', 'in', ('enabled', 'test')),
        ]).mapped('company_id')
        for move in self:
            move.mypay_can_pay = bool(
                move.move_type == 'out_invoice'
                and move.state == 'posted'
                and move.payment_state in ('not_paid', 'partial', 'in_payment')
                and not move.currency_id.is_zero(move.amount_residual)
                and move.company_id in mypay_companies
            )

    def action_mypay_open_checkout(self):
        """ Open the staff wizard to pick a MyPay gateway alias and customer phone. """
        self.ensure_one()
        if not self.mypay_can_pay:
            raise UserError(_(
                "MyPay checkout is only available for posted customer invoices with a residual"
                " amount, when the MyPay provider is enabled or in test mode."
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Pay via MyPay"),
            'res_model': 'mypay.checkout.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'active_model': 'account.move',
            },
        }
