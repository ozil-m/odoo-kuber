from odoo import models, fields, api


class LmsLounge(models.Model):
    _name = "lms.lounge"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Lounge / Branch"
    _rec_name = "name"

    name = fields.Char(required=True, string="Lounge Name", tracking=True, translate=True)
    code = fields.Char(help="Unique lounge code", string="Lounge Code", required=True, tracking=True, )
    logo = fields.Many2one(comodel_name="ir.attachment", string="Logo", required=False, ondelete="restrict",
                           tracking=True, )
    timezone = fields.Char(default="Asia/Riyadh", string="Timezone", tracking=True, )
    amenity_ids = fields.One2many('capsule', 'lounge_id', string='Amenities', tracking=True, ondelete="restrict")
    active = fields.Boolean(default=True, string="Active", tracking=True, )
    branch_id = fields.Many2one(comodel_name="res.branch", string="Branch", required=True, ondelete="restrict",
                                tracking=True, )
    sequence_id = fields.Many2one(comodel_name="ir.sequence", string="Sequence", required=False, ondelete="restrict",
                                  tracking=True, )
    access_price = fields.Float(string="Access Price", required=False, tracking=True, )
    pricelist_id = fields.Many2one(comodel_name='product.pricelist', string="Pricelist", tracking=True,
                                   help="If you change the pricelist, only newly added lines will be affected.",
                                   ondelete="restrict")
    country_id = fields.Many2one(comodel_name="res.country", string="Country", required=False, tracking=True, ondelete="restrict")
    region_id = fields.Many2one(comodel_name="res.country.region", string="Region", required=False, tracking=True, ondelete="restrict")
    state_id = fields.Many2one(comodel_name="res.country.state", string="State", required=False, tracking=True, ondelete="restrict" )
    address = fields.Char(string="Full Address", required=False, tracking=True)
    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)
    category_type = fields.Selection(
        selection=[('arrival', 'Arrival'), ('departure', 'Departure')], string="Category Type")
    longitude = fields.Char(string="Longitude", required=False, )
    latitude = fields.Char(string="Latitude", required=False, )
    timings = fields.Char(string="Timings", required=False, translate=True, )
    facilities_description = fields.Char(string="Facilities Description", required=False, translate=True, )
    services_description = fields.Char(string="Services Description", required=False, translate=True, )
    description = fields.Text(string="Description", translate=True, )
    facilities_ids = fields.Many2many(comodel_name="facilities", relation="branch_facilities_rel", column1="branch_id",
                                      column2="facility_id", string="Facilities", ondelete="restrict")
    services_ids = fields.Many2many(comodel_name="services", relation="branch_services_rel", column1="branch_id",
                                    column2="service_id", string="Services", ondelete="restrict")
    image_ids = fields.Many2many(comodel_name="ir.attachment", relation="attachment_rel", column1="branch_id",
                                 column2="attachment_id", string="Images", ondelete="restrict")

    terminal_id = fields.Many2one("res.terminal", "Terminal", tracking=True, ondelete="restrict")
    airport_id = fields.Many2one("res.airport", "Airport", tracking=True, ondelete="restrict")

    @api.model_create_multi
    def create(self, vals_list):
        """ Override create to create a new sequence for each lounge
            and assign it to the sequence_id field
        """
        IrSequence = self.env['ir.sequence'].sudo()
        for values in vals_list:
            val = {
                'name': F'{values["name"]} Lounge Orders',
                'padding': 4,
                'prefix': f"{values['code']}-%(y)s-",
                'code': "lms.lounge",
                'company_id': values.get('company_id', False), }
            values['sequence_id'] = IrSequence.create(val).id
        return super(LmsLounge, self).create(vals_list)

    def action_open_visits(self):
        """ Open lounge visits related to this lounge """
        return {
            'name': 'Lounge Visits',
            'type': 'ir.actions.act_window',
            'res_model': 'lms.visit',
            'view_mode': 'list,form',
            'domain': [('lounge_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }
