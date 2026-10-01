# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class LmsLounge(models.Model):
    _inherit = "lms.lounge"

    hayyak_app = fields.Boolean(string="Hayyak App", default=False, tracking=True)


class KcHayyakPartner(models.Model):
    _inherit = "res.partner"

    hayyak_app = fields.Boolean(string="Hayyak App", )
    passport = fields.Char(string="", required=False, )
    gender = fields.Selection(string="", selection=[('male', 'Male'), ('female', 'Female'), ], required=False, )
    birth_date = fields.Date(string="", required=False, )
    membership_id = fields.Char(string="SC MemberShip ID", required=False, )
