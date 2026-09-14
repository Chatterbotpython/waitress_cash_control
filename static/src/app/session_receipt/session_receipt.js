/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * Modeled directly on point_of_sale's own OrderReceipt
 * (point_of_sale/app/screens/receipt_screen/receipt/order_receipt.js),
 * for the same reason: this.printer.print() prints an OWL component
 * with its own client-side template, not a server-rendered PDF. This
 * is a DIFFERENT artifact from the backend "Thermal Session Report"
 * (ir.actions.report, wkhtmltopdf) — that one is the comprehensive,
 * downloadable document; this one is the quick on-the-till printout,
 * fired once right after a verified-successful close.
 *
 * `data` comes from pos.session.get_thermal_receipt_data() (see
 * models/pos_session.py) — the same underlying computation as every
 * other report in this module, just flattened to JSON-safe primitives.
 */
export class SessionReceipt extends Component {
    static template = "waitress_cash_control.SessionReceipt";
    static props = {
        data: Object,
        formatCurrency: Function,
    };
}
