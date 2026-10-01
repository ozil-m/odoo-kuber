from odoo import models, fields, api, _


class LmsFfpProgram(models.Model):
    _name = "lms.ffp.program"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "FFP Program"

    name = fields.Char(required=True, string="Program Name", tracking=True)
    code = fields.Char(required=True, string="Program Code", tracking=True)
    business_partner_ids = fields.Many2many(comodel_name="business.partner", relation="business_partner_ffp",
                                            column1="business_partner_id", column2="ffp_id", string="Business Partners",
                                            domain=[('partner_type', '=', 'airline')], ondelete="restrict", tracking=True)
    active = fields.Boolean(default=True, string="Active", tracking=True)
    logo = fields.Many2one(comodel_name="ir.attachment", string="Logo", required=False, ondelete="restrict", tracking=True)

    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)