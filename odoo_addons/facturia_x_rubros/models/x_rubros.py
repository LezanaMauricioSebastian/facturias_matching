from odoo import fields, models


class XRubros(models.Model):
    _name = "x_rubros"
    _description = "Rubros"
    _order = "x_studio_sequence, x_name"

    x_name = fields.Char(string="Descripción", required=True)
    x_active = fields.Boolean(string="Activo", default=True)
    x_studio_sequence = fields.Integer(string="Secuencia", default=10)
