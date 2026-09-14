# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ReportSaleDetails(models.AbstractModel):
    """Single source of truth for both:
      - the appended section on Odoo's own Daily Sales / Sales Details
        report (report/report_saledetails_summary.xml), and
      - the new 80mm thermal end-of-session report
        (report/thermal_session_report_templates.xml)

    Both re-render the SAME data computed here rather than each doing
    their own calculation, per the requirement not to invent a competing
    sales calculation system. Deleted/cancelled orders are added as a
    SEPARATE key (deleted_orders_summary) — they are never merged into
    or subtracted from the core sales totals, because deleted pos.order
    records are already absent from core's own orders search (its
    domain only ever matches paid/invoiced/done orders that still
    exist), so core's numbers are already correct on their own; this
    only adds visibility into what was removed, sourced from the
    permanent audit trail (which survives even a real unlink()).

    Verified against the actual installed source (17.0 stable):
    _get_report_values(docids, data=None) builds a `data` dict, sets
    data['session_ids'] (from docids when the report is triggered from
    the POS closing screen — see that method's own comment), then
    data.update(self.get_sale_details(...)) merges more keys onto the
    SAME dict without ever touching 'session_ids' again — so
    result.get('session_ids') reliably reflects the resolved sessions
    for this specific call.
    """
    _inherit = 'report.point_of_sale.report_saledetails'

    @api.model
    def _get_report_values(self, docids, data=None):
        result = super()._get_report_values(docids, data=data)
        try:
            session_ids = result.get('session_ids') or docids
            sessions = (
                self.env['pos.session'].browse(session_ids).exists()
                if session_ids else self.env['pos.session']
            )

            def session_tips(s):
                # Reuses core's own "closed orders" definition (falls
                # back to a manual filter if _get_closed_orders isn't
                # available) rather than inventing a different one —
                # same principle as everywhere else in this module.
                orders = (
                    s._get_closed_orders() if hasattr(s, '_get_closed_orders')
                    else s.order_ids.filtered(lambda o: o.state not in ('draft', 'cancel'))
                )
                return sum(orders.mapped('tip_amount'))

            result['pos_sessions_summary'] = [{
                'session_id': s.id,
                'session_name': s.name,
                'pos_name': s.config_id.name,
                # "waitress_name" is deliberately the POS CONFIG name, not
                # the logged-in res.users name: in this business, each
                # waitress has her own dedicated POS config/cash drawer,
                # and the config name IS her identity for reporting
                # purposes (multiple staff may share the same generic
                # Odoo login). This is a display-only choice — the
                # underlying audit trail still separately records the
                # real logged-in user for genuine accountability.
                'waitress_name': s.config_id.name,
                'start_at': s.start_at,
                'stop_at': s.stop_at,
                'opening_cash': s.cash_register_balance_start,
                'closing_cash_counted': s.cash_register_balance_end_real,
                'closing_cash_expected': s.cash_register_balance_end,
                'closing_cash_difference': s.cash_register_difference,
                'total_tips': session_tips(s),
                'currency_id': s.currency_id,
            } for s in sessions]

            audits = self.env['pos.order.deletion.audit']
            if session_ids:
                audits = audits.sudo().search([('session_id', 'in', list(session_ids))])
            result['deleted_orders_summary'] = [{
                'order_name': a.order_name,
                'action': a.action,
                'order_state': a.order_state,
                'amount_total': a.amount_total,
                'currency_id': a.currency_id,
                # Same reasoning as above: POS config name, not the
                # res.users name, for the "waitress" display value.
                'waitress_name': a.config_id.name if a.config_id else a.waitress_id.name,
                'deleted_by_name': a.deleted_by_id.name,
                'deletion_date': a.deletion_date,
                'reason': a.reason,
            } for a in audits]

            # Top-level, same scope as core's own 'payments'/'nbr_orders'/
            # etc. (i.e. one aggregate for this call's docids, matching
            # core's own convention — not nested per-session, since core's
            # 'payments' itself is already a single cross-docids
            # aggregate, not broken out per session).
            # "Total Sales" is literally the sum of every payment method's
            # total — not a separate calculation against order lines/
            # taxes — so it can never disagree with the Payments
            # breakdown printed alongside it.
            result['total_sales'] = sum(
                p.get('final_count', 0.0) for p in (result.get('payments') or []) if p.get('count')
            )
            result['void_count'] = len(result['deleted_orders_summary'])
            result['total_voids'] = sum(
                d['amount_total'] for d in result['deleted_orders_summary']
            )
        except Exception:
            _logger.exception(
                "waitress_cash_control: could not attach session/deleted-"
                "orders summary to the Sales Details report; the core "
                "report itself is unaffected.")
            result.setdefault('pos_sessions_summary', [])
            result.setdefault('deleted_orders_summary', [])
            result.setdefault('total_sales', 0.0)
            result.setdefault('void_count', 0)
            result.setdefault('total_voids', 0.0)
        return result
