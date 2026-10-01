from odoo import api, fields, models


def _friendly_cabin(code: str):
    return {"F": "First", "J": "Business", "W": "Premium", "Y": "Economy"}.get((code or "").upper(),
                                                                               (code or "").upper())


class AcceptanceRules(models.Model):
    _name = "acceptance.rule"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Business Partner Acceptance Rules"
    _rec_name = "display_name"
    _sql_constraints = [
        ('acceptance_rule_unique', 'unique(code)', 'Code must be unique for each Acceptance Rule.'),
    ]
    display_name = fields.Char(compute='_compute_display_name', store=True)
    active = fields.Boolean(default=True, tracking=True)
    business_partner_id = fields.Many2one("business.partner", required=True, ondelete="restrict",
                                          string="Business Partner", tracking=True)

    partner_type = fields.Selection(string="Partner Type", related="business_partner_id.partner_type", store=True)
    tier_id = fields.Many2one("lms.ffp.tier", required=False, string="FFP Tier", ondelete="restrict", tracking=True)
    ffp_program_id = fields.Many2one("lms.ffp.program", required=False, string="FFP", ondelete="restrict",
                                     tracking=True)
    cabin_class = fields.Selection([("F", "First"), ("J", "Business"), ("W", "Premium"), ("Y", "Economy")],
                                   string="Cabin Class", required=False, tracking=True)
    type = fields.Selection(
        [("class", "Class"), ("tier", "Tier"), ("business_partner", "Business Partner"), ("membership", "Membership")],
        string="Type", compute='_compute_type', store=True, tracking=True)
    name = fields.Char(string="Name", required=False, tracking=True)
    code = fields.Char(string="Code", required=False, tracking=True)
    product_main_id = fields.Many2one("product.product", string="Main Passenger Product", tracking=True,
                                      ondelete="restrict")
    eligible = fields.Boolean(string="Eligible for Lounge", default=True, tracking=True)
    allow_guest = fields.Boolean(default=False, string="Allow Guest", tracking=True)
    product_guest_id = fields.Many2one("product.product", string="Guest Product", tracking=True, ondelete="restrict")
    guest_count = fields.Integer(default=0, string="Guest Count", tracking=True)
    rank = fields.Integer(default=10, string="Rank", tracking=True)
    notes = fields.Text(string="Notes", tracking=True)
    lounge_ids = fields.Many2many("lms.lounge", string="Allowed Lounge", tracking=True, ondelete="restrict")
    date_start = fields.Date(string="Start Date", tracking=True)
    date_end = fields.Date(string="End Date", tracking=True)
    logo = fields.Many2one(comodel_name="ir.attachment", string="Logo", required=False, ondelete="restrict",
                           tracking=True)
    validation_expression = fields.Text(string="Validation Expression", required=False, tracking=True)
    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)

    @api.depends('tier_id', 'business_partner_id', 'cabin_class')
    def _compute_type(self):
        for rec in self:
            if rec.tier_id:
                rec_type = 'tier'
            elif rec.cabin_class:
                rec_type = 'class'
            else:
                rec_type = 'business_partner'
            rec.type = rec_type

    @api.depends('type', 'tier_id', 'tier_id.name', 'ffp_program_id', 'ffp_program_id.name', 'business_partner_id',
                 'business_partner_id.name', 'cabin_class', 'name')
    def _compute_display_name(self):
        for rec in self:
            partner_name = rec.business_partner_id.name
            if rec.type == 'class':
                rec.display_name = f"{partner_name} - {_friendly_cabin(rec.cabin_class)} Class"
            elif rec.type == 'tier':
                rec.display_name = f"{partner_name} - {rec.ffp_program_id.name} - {rec.tier_id.name}"
            else:
                rec.display_name = f"{partner_name} - {rec.name}"

    def action_open_visits(self):
        """ Open lounge visits related to this lounge """
        return {
            'name': 'Lounge Visits',
            'type': 'ir.actions.act_window',
            'res_model': 'lms.visit',
            'view_mode': 'list,form',
            'domain': [('acceptance_rule_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }
