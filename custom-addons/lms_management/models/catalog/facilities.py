# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class Facility(models.Model):
    _name = 'facilities'
    _description = 'Facilities'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Name", required=True, translate=True, tracking=True,)
    code = fields.Char(string="Short Code", required=True, tracking=True,)
    description = fields.Text(string="Description", translate=True, tracking=True,)
    icon = fields.Many2one(comodel_name="ir.attachment", string="Icon", required=False, tracking=True, ondelete="restrict")
    active = fields.Boolean(string='Active', default=True, tracking=True,
                            help="If unchecked, it will allow you to hide the record without deleting it.")