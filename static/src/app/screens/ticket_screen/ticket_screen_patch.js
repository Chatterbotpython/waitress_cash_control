/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

/**
 * Verified against the actual installed source
 * (addons/point_of_sale/static/src/app/screens/ticket_screen/
 * ticket_screen.js): TicketScreen already has a purpose-built hook,
 * shouldHideDeleteButton(order), used by BOTH the desktop and mobile
 * row templates to decide whether to render the trash icon at all.
 * This is the correct, sanctioned extension point — no XML template
 * override needed.
 *
 * pos.user.pos_disable_order_deletion is loaded SYNCHRONOUSLY at
 * session start (see models/pos_session.py: _loader_params_res_users),
 * piggybacked onto the exact same verified mechanism core itself uses
 * for pos.user.role — no RPC call from this file, no async timing/race
 * concern, no risk of checking the wrong group (an earlier version of
 * this patch called a manager-check RPC that turned out to check the
 * global point_of_sale.group_pos_manager rather than the per-config
 * group core actually uses; this version doesn't check any group at
 * all, it just reads the flag the backend already decided).
 *
 * The real security boundary remains server-side (models/pos_order.py
 * write() guard, gated on this same field) — this patch only prevents
 * a restricted user from being shown a button that would fail for them
 * anyway. It's still worth doing: without it, a NEVER-YET-SYNCED local
 * draft order can be discarded from the till's own in-memory state
 * before any server call happens at all (onDeleteOrder() calls
 * this.pos.removeOrder(order) — a local operation — before it
 * conditionally calls the server sync), which is a case no amount of
 * server-side restriction can address by definition: there is no
 * record to protect yet.
 */
patch(TicketScreen.prototype, {
    shouldHideDeleteButton(order) {
        return super.shouldHideDeleteButton(order) || this.pos.user.pos_disable_order_deletion;
    },
});
