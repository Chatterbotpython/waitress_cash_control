# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def unlink(self):
        """Blocks direct unlink() for everyone except a trusted internal
        (superuser/sudo) caller. The ONLY legitimate way to reach that
        sudo'd path is pos.order.deletion.wizard.action_confirm(), which
        first verifies POS Manager group membership, requires a reason,
        and writes the permanent audit record — all in the same
        transaction — before calling order.sudo().unlink().

        self.env.su is True only when running as superuser (e.g. via
        .sudo()), which a normal user's own RPC/JS-originated call can
        never be, since that always runs under their own uid. This is
        NOT a context flag a caller can set to bypass the check — it
        reflects how the call was actually authenticated.

        NOTE: if any built-in Odoo POS sync/cleanup mechanism legitimately
        calls a non-sudo pos.order.unlink() somewhere this module's
        author could not verify (core pos_order.py / frontend JS sync
        controllers were not available for review), that call would also
        be blocked here. Test offline-order sync and session recovery
        flows before relying on this in production; see README.md.
        """
        if not self.env.su:
            raise UserError(_(
                "This order cannot be cancelled or removed. Please "
                "contact the POS Manager."))
        return super().unlink()

    def write(self, vals):
        """Blocks moving an order INTO the 'cancel' state for a user
        whose res.users.pos_disable_order_deletion is checked. This is
        the everyday draft-order cancel/clear path (remove_from_ui, the
        till's trash icon, the Clear button) — it does NOT affect
        unlink() above, which remains sudo-only regardless of this flag:
        deleting an already-PAID order always goes through the manager
        wizard, unaffected by a per-user setting meant for routine
        draft handling.

        A user with the checkbox UNCHECKED (the default) is completely
        unaffected — this write proceeds exactly as core Odoo would
        handle it, with no restriction at all. No other field change is
        affected either way — ordinary POS sync, payment processing,
        invoicing, etc. proceed exactly as before.
        """
        if (vals.get('state') == 'cancel' and not self.env.su
                and self.env.user.pos_disable_order_deletion):
            raise UserError(_(
                "This order cannot be cancelled or removed. Please "
                "contact the POS Manager."))
        return super().write(vals)
