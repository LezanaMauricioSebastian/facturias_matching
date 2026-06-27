from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    x_studio_category = fields.Many2one("x_rubros", string="Rubros")
