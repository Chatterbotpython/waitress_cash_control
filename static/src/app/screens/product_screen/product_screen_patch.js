/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { _t } from "@web/core/l10n/translation";

/**
 * Verified against the actual installed source
 * (addons/point_of_sale/static/src/app/screens/product_screen/
 * product_screen.js): backspacing a selected line's quantity down to
 * empty calls updateSelectedOrderline() -> _setValue("remove") ->
 * this.currentOrder.removeOrderline(selectedLine) — a purely
 * client-side, in-memory removal (no dedicated server RPC the way
 * remove_from_ui is for the whole order; it's just reconciled on the
 * next routine order sync). Removing ANY one line when others remain
 * is normal, necessary order-editing and is left completely alone here
 * — this only intercepts the case where the line being removed is the
 * LAST one, i.e. where the result would be an empty order, which is
 * functionally equivalent to discarding the whole ticket and would
 * otherwise let pos_disable_order_deletion be bypassed entirely via
 * the numpad instead of the trash icon.
 *
 * IMPORTANT LIMITATION, stated plainly: unlike the trash icon, this
 * action has no separate server call to backstop it server-side (see
 * models/pos_order.py's docstrings for the RPC-backed cases). This is
 * a client-side-only mitigation for the visible UI path an ordinary
 * user would take — it does not defend against someone bypassing the
 * frontend entirely (e.g. via the browser console), which no
 * client-side check ever can.
 */
patch(ProductScreen.prototype, {
    _setValue(val) {
        const selectedLine = this.currentOrder.get_selected_orderline();
        if (
            val === "remove" &&
            this.pos.numpadMode === "quantity" &&
            selectedLine &&
            this.currentOrder.orderlines.length === 1 &&
            this.pos.user.pos_disable_order_deletion
        ) {
            this.popup.add(ErrorPopup, {
                title: _t("Cannot remove"),
                body: _t(
                    "This order cannot be cancelled or removed. Please "
                    + "contact the POS Manager."
                ),
            });
            return;
        }
        return super._setValue(val);
    },
});
