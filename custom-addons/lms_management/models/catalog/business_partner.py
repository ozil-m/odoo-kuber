from odoo import models, fields, api
from odoo.exceptions import ValidationError


class BusinessPartner(models.Model):
    _name = "business.partner"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Business Partner"
    _sql_constraints = [
        ('business_partner_code_unique', 'unique(code)', 'Code must be unique for each Business Partner.'),
    ]

    @api.constrains('partner_type')
    def _check_unique_cash_partner(self):
        """Allow only one record with partner_type = 'cash'."""
        for record in self:
            if record.partner_type == 'cash':
                existing = self.search([('partner_type', '=', 'cash'), ('id', '!=', record.id), ], limit=1)
                if existing:
                    raise ValidationError("Only one Business Partner of type 'Cash' is allowed.")

    def copy(self, default=None):
        """ Override copy to append (copy) to name and code of duplicated business partner"""
        default = dict(default or {})
        default['name'] = "%s (copy)" % self.name
        default['code'] = "%s (copy)" % self.code
        return super(BusinessPartner, self).copy(default)

    active = fields.Boolean(default=True, tracking=True)
    # Business Partner Info
    name = fields.Char(required=True, tracking=True)
    code = fields.Char(string="Code", required=True, tracking=True)
    partner_type = fields.Selection(string="Type",
                                    selection=[('aggregator', 'Aggregator'), ('corporate', 'Corporate'),
                                               ('cash', 'Cash'), ('airline', 'Airline'), ],
                                    required=True, tracking=True)
    logo = fields.Many2one(comodel_name="ir.attachment", string="Logo", required=False, tracking=True,
                           ondelete="restrict")
    partner_id = fields.Many2one("res.partner", string="Customer", tracking=True, ondelete="restrict")
    settlement_model = fields.Selection(
        [("fixed", "Fixed per visit"), ("revenue_share", "Revenue share %"), ("hayyak", "Hayyak Membership")],
        default="fixed", tracking=True)

    # Integration
    allow_integration = fields.Boolean(default=False, string="Integration", tracking=True)
    api_base_url = fields.Char(string="API Base URL", tracking=True)
    api_key = fields.Char(string="API Key", tracking=True)

    # Contract
    contacted_partner = fields.Boolean(default=False, string="Contacted Partner", tracking=True)
    contract_start = fields.Date(string="Contract Start", tracking=True)
    contract_end = fields.Date(string="Contract End", tracking=True)
    contract_status = fields.Selection(
        [("active", "Active"), ("running", "Running"), ("suspended", "Suspended"), ("expired", "Expired")],
        tracking=True)

    # Quota
    pax_quota = fields.Boolean(default=False, string="Pax Quota", tracking=True)
    free_pax_quota = fields.Integer(string="Free Pax Quota", help="Number of free pax allowed per quota period",
                                    tracking=True)
    used_quota = fields.Integer(compute="_compute_quota", store=False, string="Used Quota")
    remaining_quota = fields.Integer(compute="_compute_quota", store=False, string="Remaining Quota")
    quota_start = fields.Date(string="Quota Start Date", tracking=True)
    quota_end = fields.Date(string="Quota End Date", tracking=True)
    allow_access_after_quota_exceeded = fields.Boolean(default=True, string="Allow Access After Quota Exceeded",
                                                       tracking=True)

    # Airline allowed_access_rule
    allowed_access_rule = fields.Selection([("booking", "Booking Classes"), ("ffp", "FFP Tiers"), ("both", "Both")],
                                           default="both", string="Allowed Access Rule", tracking=True)

    # access_window
    access_window = fields.Boolean(default=False, string="Access Time Window", tracking=True)
    before_departure_window = fields.Integer(help="Minutes before flight departure allowed",
                                             string="Before Departure Window", default=4, tracking=True)
    after_arrival_window = fields.Integer(help="Minutes after arrival allowed", string="After Arrival Window",
                                          default=1, tracking=True)

    ffp_program_ids = fields.Many2many(comodel_name="lms.ffp.program", relation="business_partner_ffp",
                                       column1="ffp_id", column2="business_partner_id", string="FFP Programs",
                                       tracking=True)

    booking_class_acceptance_rules_ids = fields.One2many('acceptance.rule', 'business_partner_id',
                                                         string='Booking Class Rules',
                                                         domain=[('type', '=', 'class')])
    business_partner_acceptance_rules_ids = fields.One2many('acceptance.rule', 'business_partner_id',
                                                            string='Business Partner Rules', )
    ffp_tier_acceptance_rules_ids = fields.One2many('acceptance.rule', 'business_partner_id', string='FFP Tier Rules',
                                                    domain=[('type', '=', 'tier')])

    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)

    def _compute_quota(self):
        for r in self:
            r.used_quota = 0
            r.remaining_quota = max(0, (r.free_pax_quota or 0) - r.used_quota)

    def action_open_visits(self):
        """ Open the visits related to this business partner"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Visits",
            "res_model": "lms.visit",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "target": "current",
            'context': {'create': False, 'edit': False, 'delete': False},
        }
