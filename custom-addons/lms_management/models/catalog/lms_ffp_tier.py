from odoo import models, fields, api, _


class LmsFfpTier(models.Model):
    _name = "lms.ffp.tier"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "FFP Tier"

    name = fields.Char(required=True, string="Tier Name", tracking=True)
    code = fields.Char(string="Tier Code", required=True, tracking=True)
    rank = fields.Integer(default=10, string="Rank", tracking=True)
    logo = fields.Many2one(comodel_name="ir.attachment", string="Logo", required=False, ondelete="restrict", tracking=True )

    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)