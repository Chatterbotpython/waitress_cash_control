# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    pos_disable_order_deletion = fields.Boolean(
        string="Disable Order Deletion",
        default=False,
        help="If checked, this user cannot cancel, clear, or delete a "
             "POS order — from the till (trash icon, Clear button) or "
             "via direct RPC calls to pos.order. Enforced server-side; "
             "the frontend controls are hidden as a convenience, not the "
             "security boundary. Deleting an already-PAID order always "
             "goes through the separate manager wizard regardless of "
             "this setting — this only governs the everyday draft-order "
             "cancel/clear path.")
