from odoo import models, fields

class LmsOverride(models.Model):
    _name = "lms.override"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Supervisor Override"
    _order = "id desc"

    name = fields.Char(string="Override Reference", default=lambda self:self.env['ir.sequence'].next_by_code('lms.override'), copy=False)
    supervisor_id = fields.Many2one("res.users", required=True,string="Supervisor", tracking=True, ondelete="restrict")
    reason = fields.Text(required=True,string="Reason for Override", tracking=True)
    visit_id = fields.Many2one("lms.visit", required=True,string="Visit", tracking=True, ondelete="restrict")
    passenger_line_ids = fields.One2many("lms.override.passenger", "override_id",string="Passengers")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments", tracking=True)
    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)

class LmsOverridePassenger(models.Model):
    _name = "lms.override.passenger"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Override Passenger Line"

    override_id = fields.Many2one("lms.override", required=True, ondelete="restrict",string="Override")
    passenger_name = fields.Char(string="Passenger Name", tracking=True)
    notes = fields.Char(string="Notes")
    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)
