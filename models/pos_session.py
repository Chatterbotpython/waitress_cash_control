# -*- coding: utf-8 -*-
import base64
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        """Generates the thermal end-of-session report as a stored
        attachment AFTER a successful close — never before, never on
        failure.

        This is safe by construction: per the verified source of this
        method, on success it returns exactly {'successful': True} and
        on failure {'successful': False, ...} or a raised exception. We
        only act on the successful case, and — critically — we return
        the EXACT SAME result object untouched either way, so the
        frontend's handling of this call is completely unaffected. This
        is the lesson from an earlier mistake in a different module on
        this same site: overriding action_pos_session_close() to swap
        in a different return value broke the frontend, because that
        method's result is inspected by close_session_from_ui() itself
        (isinstance(result, dict) is treated as a failure/redirect).
        Here we do the opposite: observe the result, change nothing
        about it, and do our extra work as a side effect that cannot
        affect what the till screen sees.

        We do not attempt to trigger a print dialog inside the POS
        register UI itself — that requires the frontend JS that calls
        this method, which was not available for review. The generated
        PDF is available as an attachment on this session (and via the
        Sessions form in the backend) immediately after closing.
        """
        result = super().close_session_from_ui(
            bank_payment_method_diff_pairs=bank_payment_method_diff_pairs)
        if isinstance(result, dict) and result.get('successful'):
            try:
                self._generate_thermal_session_report_attachment()
            except Exception:
                _logger.exception(
                    "waitress_cash_control: session %s closed successfully "
                    "but the thermal report attachment could not be "
                    "generated; the session close itself is unaffected.",
                    self.name)
        return result

    def _generate_thermal_session_report_attachment(self):
        self.ensure_one()
        report = self.env.ref('waitress_cash_control.action_thermal_session_report')
        pdf_content, _report_type = report.sudo()._render_qweb_pdf(
            report.report_name, [self.id])
        return self.env['ir.attachment'].sudo().create({
            'name': 'Thermal Session Report - %s.pdf' % (self.name or self.id),
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': 'pos.session',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

    def action_print_thermal_session_report(self):
        """Manual/backend equivalent — always available regardless of
        how the session was closed, e.g. for a session closed from the
        backend form (action_pos_session_closing_control) rather than
        the POS till UI. Only usable once the session is actually
        closed, so it can never print a report for a session whose
        close failed or hasn't happened yet.
        """
        self.ensure_one()
        if self.state != 'closed':
            raise UserError(_("This session is not closed yet."))
        return self.env.ref(
            'waitress_cash_control.action_thermal_session_report'
        ).report_action(self, config=False)

    def get_thermal_receipt_data(self):
        """RPC-callable (called from the POS frontend's closing popup
        patch, static/src/app/navbar/closing_popup/closing_popup_patch.js,
        right after a verified-successful close_session_from_ui). Returns
        a plain, JSON-safe dict for the client-side SessionReceipt OWL
        component to render and send to the printer service — the same
        technology used for the ordinary sale receipt (OrderReceipt),
        which cannot render a server-side PDF.

        Deliberately reuses report.point_of_sale.report_saledetails.
        _get_report_values() — the exact same computation as the Daily
        Sales report and the backend Thermal Session Report PDF — rather
        than computing anything independently, then narrows/flattens it
        to JSON-safe primitives (datetimes as ISO strings, no recordsets)
        since this crosses the JSON-RPC boundary directly rather than
        going through ORM read() serialization.
        """
        self.ensure_one()
        values = self.env['report.point_of_sale.report_saledetails']._get_report_values([self.id])
        session_summary = (values.get('pos_sessions_summary') or [{}])[0]

        def iso(dt):
            return fields.Datetime.to_string(dt) if dt else False

        payments = [{
            'name': p.get('name'),
            'final_count': p.get('final_count'),
        } for p in (values.get('payments') or []) if p.get('count')]

        deleted_orders = [{
            'order_name': d['order_name'],
            'action': d['action'],
            'amount_total': d['amount_total'],
            'waitress_name': d['waitress_name'],
            'reason': d['reason'],
        } for d in (values.get('deleted_orders_summary') or [])]

        return {
            'company_name': values.get('company_name'),
            'session_name': values.get('session_name') or self.name,
            'pos_name': session_summary.get('pos_name') or self.config_id.name,
            'waitress_name': session_summary.get('waitress_name') or self.config_id.name,
            'start_at': iso(self.start_at),
            'stop_at': iso(self.stop_at),
            'nbr_orders': values.get('nbr_orders'),
            'currency': values.get('currency'),
            'opening_cash': session_summary.get('opening_cash'),
            'closing_cash_counted': session_summary.get('closing_cash_counted'),
            'closing_cash_expected': session_summary.get('closing_cash_expected'),
            'closing_cash_difference': session_summary.get('closing_cash_difference'),
            'total_tips': session_summary.get('total_tips'),
            # total_sales/void_count/total_voids are computed once, in
            # report_sale_details.py, and simply read here — same
            # numbers as the backend Thermal PDF and the Daily Sales
            # appended section, never a separate calculation.
            'total_sales': values.get('total_sales'),
            'payments': payments,
            'discount_number': values.get('discount_number'),
            'discount_amount': values.get('discount_amount'),
            'void_count': values.get('void_count'),
            'total_voids': values.get('total_voids'),
            'deleted_orders': deleted_orders,
        }

    @api.model
    def is_current_user_pos_manager(self):
        """RPC-callable, deliberately independent of any specific
        session (called with an empty recordset from the frontend).
        Kept for the backend order-form button visibility only. NOT
        used for the till's delete-button visibility anymore — see
        res_users.py / ticket_screen_patch.js for why: that check now
        reads pos.user.pos_disable_order_deletion directly (loaded
        synchronously at session start via the verified
        _loader_params_res_users pattern below), which is both more
        reliable and correctly scoped, unlike this method, which checks
        the GLOBAL point_of_sale.group_pos_manager rather than the
        PER-CONFIG group (config_id.group_pos_manager_id) that core
        itself uses to compute pos.user.role.
        """
        return self.env.user.has_group('point_of_sale.group_pos_manager')

    def _loader_params_res_users(self):
        """Piggybacks pos_disable_order_deletion onto core's own
        verified res.users loader (addons/point_of_sale/models/
        pos_session.py: _loader_params_res_users /
        _get_pos_ui_res_users), so it lands on the frontend's
        this.pos.user synchronously at session start — the same
        mechanism core uses for pos.user.role. No extra RPC, no
        onWillStart timing/race concerns.
        """
        result = super()._loader_params_res_users()
        result['search_params']['fields'].append('pos_disable_order_deletion')
        return result
