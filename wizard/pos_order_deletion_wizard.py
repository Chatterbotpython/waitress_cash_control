# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class PosOrderDeletionWizard(models.TransientModel):
    """The ONLY path that can actually cancel or delete a pos.order.
    Everything here runs server-side regardless of how it was invoked
    (UI button or direct RPC to this wizard's own methods), and the
    manager-group check happens on self.env.user BEFORE any .sudo() is
    used, so authorization is checked against the real acting user.
    """
    _name = 'pos.order.deletion.wizard'
    _description = 'Manager: Cancel or Delete a POS Order'

    order_id = fields.Many2one('pos.order', string='Order', required=True, readonly=True)
    order_name = fields.Char(related='order_id.name', string='Reference', readonly=True)
    order_state = fields.Char(string='Current State', readonly=True)
    has_accounting_impact = fields.Boolean(
        string='Has Accounting/Stock Impact', readonly=True,
        help="True if this order already has a linked invoice "
             "(account_move) or stock pickings. Deleting it will NOT "
             "corrupt or delete that posted journal entry or those "
             "pickings — they are independent records — but they will "
             "become orphaned from their source POS order, breaking "
             "traceability. Consider 'Cancel' instead of 'Delete' for "
             "orders like this.")
    action = fields.Selection(
        [('cancel', 'Cancel (keep the record, mark as Cancelled)'),
         ('delete', 'Delete (permanently remove the record)')],
        string='Action', required=True, default='cancel')
    reason = fields.Text(string='Reason', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            order = self.env['pos.order'].browse(active_id)
            if 'order_id' in fields_list:
                res['order_id'] = active_id
            if 'order_state' in fields_list:
                res['order_state'] = order.state
                # Paid/confirmed orders should default to the (heavier)
                # delete action being a deliberate choice, not a
                # pre-selected default — keep 'cancel' as the safe default
                # for both cases; the manager explicitly picks 'delete'.
            if 'has_accounting_impact' in fields_list:
                res['has_accounting_impact'] = bool(order.account_move or order.picking_ids)
        return res

    def _check_manager(self):
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_(
                "Only a Point of Sale Administrator can cancel or remove an order."))

    def _snapshot_order(self, order):
        """Best-effort snapshot for the audit trail. Wrapped so that a
        problem building the snapshot (e.g. an unexpected data shape)
        never blocks the actual, more important cancel/delete + audit
        creation below — an audit row with a thinner snapshot is far
        better than silently failing to let a manager do their job.
        """
        lines_snapshot, payments_snapshot = [], []
        try:
            for line in order.lines:
                lines_snapshot.append({
                    'product': line.product_id.display_name,
                    'qty': line.qty,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'price_subtotal': line.price_subtotal,
                    'price_subtotal_incl': line.price_subtotal_incl,
                    'taxes': line.tax_ids_after_fiscal_position.mapped('name'),
                })
        except Exception:
            _logger.exception(
                "waitress_cash_control: could not snapshot order lines "
                "for order %s; audit will still be created without this "
                "detail.", order.name)
        try:
            payments = self.env['pos.payment'].search([('pos_order_id', '=', order.id)])
            for payment in payments:
                payments_snapshot.append({
                    'payment_method': payment.payment_method_id.name,
                    'amount': payment.amount,
                })
        except Exception:
            _logger.exception(
                "waitress_cash_control: could not snapshot payments for "
                "order %s; audit will still be created without this "
                "detail.", order.name)
        return lines_snapshot, payments_snapshot

    def action_confirm(self):
        self.ensure_one()
        self._check_manager()
        if not (self.reason or '').strip():
            raise UserError(_("A reason is required to cancel or remove an order."))

        order = self.order_id
        if not order.exists():
            raise UserError(_("This order no longer exists."))

        lines_snapshot, payments_snapshot = self._snapshot_order(order)

        # Audit is written FIRST, in the same DB transaction as the
        # cancel/delete that follows. Nothing in this method commits
        # early, so if anything below raises, everything (including
        # this audit row) rolls back together — the audit can never
        # exist without the action having actually happened, and the
        # action can never happen without the audit existing.
        self.env['pos.order.deletion.audit'].sudo().create({
            'action': self.action,
            'order_name': order.name,
            'order_id': order.id,
            'order_date': order.date_order,
            'order_state': order.state,
            'amount_total': order.amount_total,
            'currency_id': order.session_id.currency_id.id if order.session_id else False,
            'config_id': order.config_id.id if order.config_id else False,
            'session_id': order.session_id.id if order.session_id else False,
            'waitress_id': order.user_id.id if order.user_id else False,
            'order_lines_snapshot': json.dumps(lines_snapshot),
            'payments_snapshot': json.dumps(payments_snapshot),
            'deleted_by_id': self.env.user.id,
            'reason': self.reason,
        })

        if self.action == 'delete':
            # Core has an @api.ondelete hook on pos.order
            # (_unlink_except_draft_or_cancel, verified in the actual
            # installed source) that unconditionally rejects unlink() on
            # any order not already in 'draft' or 'cancel' state — and
            # @api.ondelete hooks are NOT bypassed by .sudo(). Core's own
            # remove_from_ui() follows this exact cancel-then-unlink
            # sequence for the same reason; we mirror it rather than
            # inventing a different one.
            order.sudo().write({'state': 'cancel'})
            order.mapped('payment_ids').sudo().unlink()
            order.sudo().unlink()
        else:
            order.sudo().write({'state': 'cancel'})

        return {'type': 'ir.actions.act_window_close'}
