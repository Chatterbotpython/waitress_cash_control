# -*- coding: utf-8 -*-
from odoo import api, models


class ReportThermalSessionReport(models.AbstractModel):
    """Thin delegate: the thermal report renders the exact same data as
    the (extended) core Sales Details report — see report_sale_details.py
    for why, and for where pos_sessions_summary / deleted_orders_summary
    come from. This file exists only to give the thermal report's own
    ir.actions.report a report-values provider under its own name,
    without duplicating any calculation.
    """
    _name = 'report.waitress_cash_control.report_thermal_session'
    _description = 'Thermal Session Report (data provider)'

    @api.model
    def _get_report_values(self, docids, data=None):
        return self.env['report.point_of_sale.report_saledetails']._get_report_values(docids, data=data)
