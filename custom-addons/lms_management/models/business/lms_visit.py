# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .utils_bcbp import parse_bcbp, convert_julian_to_date


def _split_first_last(name_raw: str, name_clean: str):
    last_name = ""
    first_name = ""
    s = (name_raw or "").strip()
    if "/" in s:
        left, right = s.split("/", 1)
        last_name = (left or "").strip()
        first_name = (right or "").strip()
    else:
        parts = (name_clean or "").split()
        if parts:
            last_name = parts[0]
            first_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first_name, last_name


class LmsVisit(models.Model):
    _name = "lms.visit"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Lounge Visit"
    _order = "id desc"

    name = fields.Char(copy=False, string="Visit Reference", tracking=True)
    lounge_id = fields.Many2one("lms.lounge", string="Lounge", required=True, ondelete="restrict", tracking=True)
    branch_id = fields.Many2one("res.branch", string="Branch", related="lounge_id.branch_id", store=True,
                                ondelete="restrict", tracking=True)
    access_method = fields.Selection([('class', 'Airline Class'),
                                      ('ffp', 'FFP Tier'),
                                      ('aggregator', 'Aggregator'),
                                      ('corporate', 'Corporate'),
                                      ('prebooking', 'Pre-booking'),
                                      ('cash', 'Cash'), ], required=True, default='class', string="Access Method",
                                     tracking=True)
    access_date = fields.Datetime(string="Access Date & Time", tracking=True)
    airline_id = fields.Many2one("business.partner", string="Airline", domain="[('partner_type','=','airline')]",
                                 ondelete="restrict", tracking=True)
    acceptance_rule_id = fields.Many2one("acceptance.rule", readonly=False, string="Acceptance Rule",
                                         ondelete="restrict", tracking=True)
    business_partner_id = fields.Many2one("business.partner", ondelete="restrict",
                                          string="Business Partner", related='acceptance_rule_id.business_partner_id',
                                          store=True, tracking=True)
    access_doc_id = fields.Char(string="Access Document ID", required=False, tracking=True)
    booking_ref = fields.Char(string="Booking Reference / PNR")
    partner_id = fields.Many2one("res.partner", string="Customer", ondelete="restrict",
                                 related="business_partner_id.partner_id", store=True, tracking=True)
    state = fields.Selection(string="Status",
                             selection=[('draft', 'Draft'), ('confirmed', 'Confirmed'), ('cancelled', 'Cancelled'), ],
                             required=False, default='draft', tracking=True, copy=False)
    payment_method_id = fields.Many2one("account.journal", domain=[('type', 'in', ('cash', 'bank'))],
                                        string="Payment Method", ondelete="restrict", tracking=True)
    invoicing_status = fields.Selection(
        [('to_invoice', 'To Invoice'), ('invoiced', 'Invoiced'), ('refunded', 'Refunded'), ], tracking=True, copy=False,
        default='to_invoice', string="Invoicing Status", help=(
            "Indicates the Invoicing progress of the visit:\n"
            "- To Invoice: The visit is ready to be invoiced.\n"
            "- Invoiced: The visit has been invoiced.\n"
            "- Refunded: The invoice has been refunded.\n"
        ), )
    notes = fields.Text(string="Internal Notes", tracking=True)
    # Editable relateds (these are what you place in groups on the Visit form)
    passenger_title = fields.Char(readonly=False, string="Passenger Name")
    first_name = fields.Char(readonly=False, string="First Name")
    last_name = fields.Char(readonly=False, string="Last Name")
    pnr = fields.Char(readonly=False, string="PNR")
    airline_code = fields.Char(readonly=False, string="Airline Code")
    class_code = fields.Char(readonly=False, string="Class Code", tracking=True)
    ffp_program_id = fields.Many2one(comodel_name="lms.ffp.program", string="FFP Program", required=False,
                                     related="acceptance_rule_id.ffp_program_id", store=True, ondelete="restrict",
                                     tracking=True)
    tier_id = fields.Many2one(comodel_name="lms.ffp.tier", string="FFP Tier", required=False,
                              related="acceptance_rule_id.tier_id", store=True, ondelete="restrict", tracking=True)
    seat_number = fields.Char(readonly=False, string="Seat Number")
    flight_number = fields.Char(readonly=False, string="Flight Number")
    flight_sequence = fields.Char(readonly=False, string="Flight Seq No")
    flight_from = fields.Char(readonly=False, string="From")
    flight_to = fields.Char(readonly=False, string="To")
    flight_date = fields.Date(readonly=False, string="Flight Date")
    ticket = fields.Char(readonly=False, string="Ticket Number")
    fqtv = fields.Char(readonly=False, string="Frequent Flyer")
    product_id = fields.Many2one(comodel_name="product.product", string="Product", required=False, ondelete="restrict",
                                 tracking=True)
    product_price = fields.Float(readonly=False, string="Product Price", tracking=True)
    boarding_pass_raw = fields.Text(readonly=False, string="Raw Boarding Pass", tracking=True)
    type = fields.Selection([('main', 'Main'), ('guest', 'Guest')], string="Type", required=True, default='main',
                            tracking=True)
    class_name = fields.Char("Cabin Name", compute="_compute_class_name", store=True, tracking=True)
    parent_id = fields.Many2one(comodel_name="lms.visit", string="Parent", required=False, ondelete="restrict",
                                tracking=True, copy=False)
    child_ids = fields.One2many(comodel_name="lms.visit", inverse_name="parent_id", string="Childs", required=False, )
    childs_count = fields.Float(string='Guests', compute='_compute_childs_count', store=True)
    uuid = fields.Char(string='uuid', tracking=True, copy=False)
    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)
    voucher_id = fields.Many2one(comodel_name="lounge.voucher", string="E-Voucher", readonly=True, tracking=True)

    def action_open_voucher(self):
        """ Open the voucher associated with this visit."""
        self.ensure_one()
        if not self.voucher_id:
            raise UserError(_("No voucher is associated with this visit."))
        return {
            "type": "ir.actions.act_window",
            "name": _("E-Voucher"),
            "res_model": "lounge.voucher",
            "view_mode": "form",
            "res_id": self.voucher_id.id,
            "target": "current",
        }

    def action_cancel(self):
        """ Cancel the visit"""
        for rec in self:
            rec.state = 'cancelled'

    @api.depends("child_ids")
    def _compute_childs_count(self):
        for rec in self:
            rec.childs_count = len(rec.child_ids)

    @api.depends('dependency_field')
    def _compute_computed_field(self):
        """Compute the value of the field computed_field."""
        for record in self:
            record.computed_field = 0.0  # Your computation here

    @api.depends('acceptance_rule_id.cabin_class', 'class_code')
    def _compute_class_name(self):
        label_map = {'F': 'First', 'J': 'Business', 'W': 'Premium', 'Y': 'Economy'}
        for rec in self:
            class_name = False
            if rec.acceptance_rule_id.cabin_class:
                code = (rec.acceptance_rule_id.cabin_class or rec.class_code or '').upper()
                rec.class_name = label_map.get(code, code)
            rec.class_name = class_name

    @api.model_create_multi
    def create(self, vals_list):
        """Guarantee a blank 'main' passenger exists so main_* fields are always writable."""
        records = super().create(vals_list)
        for rec in records:
            rec.name = rec.lounge_id.sequence_id._next()
        return records

    # -------- Helpers for BCBP parsing --------

    def _find_airline_by_code(self, code: str):
        code = (code or "").replace(" ", "").upper()
        code2 = code[:2]
        airline_model = self.env['business.partner'].sudo()
        airline = airline_model.search([('code', '=', code2), ('partner_type', '=', 'airline')], limit=1)
        if not airline and code2:
            airline = airline_model.search([('code', 'ilike', code2), ('partner_type', '=', 'airline')], limit=1)
        return airline

    def _find_rule(self, airline, compartment_code):
        if not airline:
            return self.env['acceptance.rule']
        rule_model = self.env['acceptance.rule'].sudo()
        dom = [('business_partner_id', '=', airline.id), ('type', '=', 'class')]
        if compartment_code:
            dom.append(('cabin_class', '=', (compartment_code or '').upper()))
        return rule_model.search(dom, order="rank asc, id asc", limit=1)

    def action_parse_bcbp_and_add_main(self, bcbp_string):
        """Parse BCBP and write into the main passenger line (create one if needed)."""
        self.ensure_one()
        if not bcbp_string:
            raise UserError(_("BCBP string is empty."))

        data = parse_bcbp(bcbp_string)

        airline = self._find_airline_by_code(data.operating_carrier)
        rule = self._find_rule(airline, data.compartment_code)

        product_id = False
        product_price = 0.0
        if rule and rule.product_id:
            product_id = rule.product_id.id
            try:
                product_price = rule.product_id.lst_price
            except Exception:
                product_price = 0.0

        flight_date = convert_julian_to_date(data.flight_date_julian)
        first_name, last_name = _split_first_last(data.passenger_name_raw, data.passenger_name)
        vals = {
            # "visit_id": self.id,  # not needed when writing existing main
            "type": "main",
            "boarding_pass_raw": bcbp_string,
            "passenger_title": (data.passenger_name or "").strip(),
            "first_name": first_name,
            "last_name": last_name,
            "pnr": data.pnr or "",
            "airline_code": (data.operating_carrier or "").upper(),
            "airline_id": airline.id if airline else False,
            "class_code": (data.compartment_code or "").upper(),
            "class_id": rule.id if rule else False,
            "seat_number": (data.seat_number or "").upper(),
            "flight_number": (data.flight_number or ""),
            "flight_sequence": data.check_in_sequence or "",
            "flight_from": (data.from_airport or "").upper(),
            "flight_to": (data.to_airport or "").upper(),
            "flight_date": flight_date,
            "ticket": data.ticket_number or "",
            "fqtv": data.fqtv or "",
            "product_id": product_id,
            "product_price": product_price,
        }

        return True

    def action_parse_bcbp(self):
        """Parse BCBP and write into the main passenger line (create one if needed)."""
        self.ensure_one()
        if not self.boarding_pass_raw:
            raise UserError(_("BCBP string is empty."))
        if not self.type:
            raise UserError(_("Passenger type is not set."))
        if not self.lounge_id:
            raise UserError(_("Lounge is not set on the visit."))
        if not self.lounge_id.pricelist_id:
            raise UserError(_("Lounge has no pricelist set."))
        data = parse_bcbp(self.boarding_pass_raw)

        airline = self._find_airline_by_code(data.operating_carrier)
        rule = self._find_rule(airline, data.compartment_code)

        product_id = False
        product_price = 0.0
        if rule:
            rule_product = rule.product_main_id if self.type == 'main' else rule.product_guest_id
            if rule_product:
                product_id = rule_product.id
                product_price = self.lounge_id.pricelist_id._get_product_price(rule_product, 1.0, )

        flight_date = convert_julian_to_date(data.flight_date_julian)
        first_name, last_name = _split_first_last(data.passenger_name_raw, data.passenger_name)
        vals = {
            "type": "main",
            "boarding_pass_raw": self.boarding_pass_raw,
            "passenger_title": (data.passenger_name or "").strip(),
            "first_name": first_name,
            "last_name": last_name,
            "pnr": data.pnr or "",
            "airline_code": (data.operating_carrier or "").upper(),
            "airline_id": airline.id if airline else False,
            "class_code": (data.compartment_code or "").upper(),
            "acceptance_rule_id": rule.id if rule else False,
            "seat_number": (data.seat_number or "").upper(),
            "flight_number": (data.flight_number or ""),
            "flight_sequence": data.check_in_sequence or "",
            "flight_from": (data.from_airport or "").upper(),
            "flight_to": (data.to_airport or "").upper(),
            "flight_date": flight_date,
            "ticket": data.ticket_number or "",
            "fqtv": data.fqtv or "",
            "product_id": product_id,
            "product_price": product_price,
        }
        self.write(vals)
        if not rule:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Acceptance Rule Found',
                    'message': "No acceptance rule found for airline %s and class %s." % (
                        (airline.name or data.operating_carrier or "").upper(), (data.compartment_code or "").upper()),
                    'sticky': True,
                }
            }

        return True

    def action_open_child_ids(self):
        """ Open a window to show child visits (guests)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Guests"),
            "res_model": "lms.visit",
            "view_mode": "list,form",
            "domain": [("id", "in", self.child_ids.ids)],
            "target": "current",
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def unlink(self):
        """ Override unlink to prevent deletion of non-draft visits."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft visits can be deleted."))
        return super().unlink()

    def action_confirm(self):
        """ Confirm the visit"""
        for rec in self:
            rec.state = 'confirmed'
