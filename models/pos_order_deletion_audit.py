# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class PosOrderDeletionAudit(models.Model):
    """Permanent, read-only-after-creation record of every manager
    cancellation/removal of a pos.order. Created by
    pos.order.deletion.wizard BEFORE the underlying order is touched, in
    the same database transaction, so the two either both succeed or
    both roll back together (Odoo wraps one controller call in one
    transaction; no manual commit is used anywhere in this flow).

    order_id is a plain Integer (not a Many2one) because the referenced
    pos.order may be genuinely deleted (unlink action) — a Many2one
    would go stale or cascade-null. Everything needed to reconstruct
    what the order was is snapshotted onto this record at deletion time.
    """
    _name = 'pos.order.deletion.audit'
    _description = 'POS Order Deletion/Cancellation Audit'
    _order = 'deletion_date desc'

    action = fields.Selection(
        [('cancel', 'Cancelled (kept, state set to Cancelled)'),
         ('delete', 'Deleted (record permanently removed)')],
        string='Action', required=True, readonly=True)

    # --- Identity of the original order (snapshotted; order_id itself
    # may no longer exist by the time this is read) ---
    order_name = fields.Char(string='Order Reference', required=True, readonly=True)
    order_id = fields.Integer(string='Original Order ID', required=True, readonly=True)
    order_date = fields.Datetime(string='Order Date', readonly=True)
    order_state = fields.Selection(
        [('draft', 'New'), ('paid', 'Paid'), ('done', 'Posted'),
         ('invoiced', 'Invoiced'), ('cancel', 'Cancelled')],
        string='Order State At Deletion', readonly=True)
    amount_total = fields.Monetary(string='Order Total', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    # --- Where it happened (kept as real relations: these records are
    # never deleted, so it's safe to link to them) ---
    config_id = fields.Many2one('pos.config', string='Point of Sale', readonly=True, index=True)
    session_id = fields.Many2one('pos.session', string='Session', readonly=True, index=True)
    waitress_id = fields.Many2one('res.users', string='Waitress / POS User', readonly=True, index=True)

    # --- Full snapshot (JSON text) so the order's content survives
    # even after a real unlink() ---
    order_lines_snapshot = fields.Text(
        string='Order Lines (JSON)', readonly=True,
        help="List of {product, qty, price_unit, discount, taxes, subtotal} "
             "as they were at the moment of deletion.")
    payments_snapshot = fields.Text(
        string='Payments (JSON)', readonly=True,
        help="List of {payment_method, amount} as they were at the moment "
             "of deletion.")

    # --- Who did it and why ---
    deleted_by_id = fields.Many2one(
        'res.users', string='Deleted/Removed By', required=True, readonly=True)
    deletion_date = fields.Datetime(
        string='Deletion Timestamp', required=True, readonly=True,
        default=fields.Datetime.now)
    reason = fields.Text(string='Reason', required=True, readonly=True)

    def write(self, vals):
        raise UserError(_(
            "Audit records are permanent and cannot be modified, by design."))

    def unlink(self):
        raise UserError(_(
            "Audit records are permanent and cannot be deleted, by design."))
