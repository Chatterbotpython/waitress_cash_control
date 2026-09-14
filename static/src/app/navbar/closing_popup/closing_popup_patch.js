/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { SessionReceipt } from "@waitress_cash_control/app/session_receipt/session_receipt";
import { useService } from "@web/core/utils/hooks";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { ConnectionLostError } from "@web/core/network/rpc_service";
import { _t } from "@web/core/l10n/translation";
import { parseFloat } from "@web/views/fields/parsers";

/**
 * Patches ClosePosPopup (addons/point_of_sale/static/src/app/navbar/
 * closing_popup/closing_popup.js, verified against this install's
 * actual 17.0 source) to print a quick session receipt right after a
 * successful close, before the app redirects away from the till.
 *
 * WHY A FULL METHOD OVERRIDE, NOT A SMALLER PATCH:
 * redirectToBackend() is called from TWO places in the verified
 * source: once on genuine success, and once in the generic-error catch
 * branch (a failed close that still sends the cashier back to the
 * backend to finish manually). There is no separate, smaller method
 * that only runs on success — the branch lives inline inside
 * closeSession() itself. Patching only "whenever redirectToBackend is
 * called" would therefore also print on that failure path, which is
 * exactly what "Do NOT print if the close fails" rules out. The
 * narrowest correct hook available in the verified source is this
 * exact spot, which means overriding the whole method.
 *
 * MAINTENANCE: everything below the `setup` patch is copied verbatim
 * from the verified closing_popup.js, with ONE addition clearly marked
 * with >>> / <<< waitress_cash_control comments. If you upgrade Odoo
 * and this stops working, diff this method against the new core
 * closing_popup.js — the only intentional difference should be that
 * one block.
 */
patch(ClosePosPopup.prototype, {
    setup() {
        super.setup();
        this.printer = useService("printer");
    },

    async closeSession() {
        this.customerDisplay?.update({ closeUI: true });
        // If there are orders in the db left unsynced, we try to sync.
        const syncSuccess = await this.pos.push_orders_with_closing_popup();
        if (!syncSuccess) {
            return;
        }
        if (this.pos.config.cash_control) {
            const response = await this.orm.call(
                "pos.session",
                "post_closing_cash_details",
                [this.pos.pos_session.id],
                {
                    counted_cash: parseFloat(
                        this.state.payments[this.props.default_cash_details.id].counted
                    ),
                }
            );

            if (!response.successful) {
                return this.handleClosingError(response);
            }
        }

        try {
            await this.orm.call("pos.session", "update_closing_control_state_session", [
                this.pos.pos_session.id,
                this.state.notes,
            ]);
        } catch (error) {
            // We have to handle the error manually otherwise the validation check stops the script.
            // In case of "rescue session", we want to display the next popup with "handleClosingError".
            // FIXME
            if (!error.data && error.data.message !== "This session is already closed.") {
                throw error;
            }
        }

        try {
            const bankPaymentMethodDiffPairs = this.props.other_payment_methods
                .filter((pm) => pm.type == "bank")
                .map((pm) => [pm.id, this.getDifference(pm.id)]);
            const response = await this.orm.call("pos.session", "close_session_from_ui", [
                this.pos.pos_session.id,
                bankPaymentMethodDiffPairs,
            ]);
            if (!response.successful) {
                return this.handleClosingError(response);
            }

            // >>> waitress_cash_control: print session receipt on success,
            // before the redirect below navigates away from the till.
            // Wrapped in try/catch so a printer problem (offline, no
            // paper, RPC hiccup) can NEVER block the redirect — the
            // session is already closed successfully at this point, and
            // the comprehensive PDF version of this same report is still
            // available as a session attachment and via the backend
            // "Print Thermal Report" button regardless of whether this
            // on-till printout succeeds.
            try {
                const receiptData = await this.orm.call(
                    "pos.session",
                    "get_thermal_receipt_data",
                    [this.pos.pos_session.id]
                );
                await this.printer.print(
                    SessionReceipt,
                    { data: receiptData, formatCurrency: this.env.utils.formatCurrency },
                    { webPrintFallback: true }
                );
            } catch (printError) {
                console.error(
                    "waitress_cash_control: failed to print the session receipt",
                    printError
                );
            }
            // <<< waitress_cash_control

            this.pos.redirectToBackend();
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                // Cannot redirect to backend when offline, let error handlers show the offline popup
                // FIXME POSREF: doing this means closing again when online will redo the beginning of the method
                // although it's impossible to close again because this.closeSessionClicked isn't reset to false
                // The application state is corrupted.
                throw error;
            } else {
                // FIXME POSREF: why are we catching errors here but not anywhere else in this method?
                await this.popup.add(ErrorPopup, {
                    title: _t("Closing session error"),
                    body: _t(
                        "An error has occurred when trying to close the session.\n" +
                            "You will be redirected to the back-end to manually close the session."
                    ),
                });
                this.pos.redirectToBackend();
            }
        }
    },
});
