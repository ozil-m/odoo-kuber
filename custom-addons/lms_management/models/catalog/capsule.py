# -*- coding: utf-8 -*-
import pytz
from odoo import models, fields, api, exceptions
from datetime import timedelta, datetime, time
from odoo.tools.date_utils import start_of, end_of, add


def convert_datetime_to_timezone(datetime_field):
    """ Convert a datetime field to a specific timezone and format it.
    """
    from datetime import datetime
    if datetime_field:
        # Convert datetime field to a datetime object
        if isinstance(datetime_field, str):
            datetime_field = datetime.strptime(datetime_field, '%Y-%m-%d %H:%M:%S')
        new_datetime_field = datetime_field
        if datetime_field.hour not in [0, 23]:
            new_datetime_field = add(datetime_field, hours=3)
        formatted_dt = new_datetime_field.strftime('%H:%M')
        return formatted_dt
    else:
        return False


def split_into_sublists(input_list, max_length=6):
    """ Split a list into sublists of a maximum length.
    """
    return [input_list[i:i + max_length] for i in range(0, len(input_list), max_length)]


def _prepare_slot(from_time, to_time, current_time, available=True, reservation_id=False):
    color = '#4caf50' if from_time >= current_time and available else '#ff7e5f'
    slot_type = 'green' if available else 'red'
    status = 'available' if available else 'not_available'
    date_now = add(fields.Datetime.now(), hours=3)
    # Calculate date differences
    date_start = start_of(from_time, 'day')
    date_end = start_of(date_now, 'day')
    delta = date_end - date_start
    total_minutes = 0
    duration_lock = 0

    # If the time difference between the current day and the slot's start is more than a day
    if reservation_id:
        from_reservation_time = reservation_id.date_from
        # to_time = reservation_id.date_to
        delta_duration = from_reservation_time - date_now
        duration_lock = reservation_id.capsule_id.duration_lock
        # Total minutes calculation
        if from_reservation_time > date_now:
            total_minutes = delta_duration.total_seconds() / 60
    #
    if delta.days >= 1 or reservation_id:
        color = '#ff7e5f'
        status = 'not_available'
        slot_type = 'red'

    return {
        'color': color,
        'type': slot_type,
        'date': fields.Date.today(),
        'status': status,
        'edit': total_minutes > duration_lock,
        'cancel': total_minutes > duration_lock,
        'duration_cancel': total_minutes,  # Return total minutes
        'reservation_id': reservation_id.id if reservation_id else False,
        'id': False,
        'from': convert_datetime_to_timezone(from_time),
        'to': convert_datetime_to_timezone(to_time)
    }


class CapsuleService(models.Model):
    _name = "capsule.service"
    _rec_name = "name"
    _description = "Capsules Service Category"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Name", required=True, tracking=True, translate=True, )
    icon = fields.Many2one(comodel_name="ir.attachment", string="Icon", required=False, ondelete="restrict",
                           tracking=True)
    description = fields.Text(string="Description", required=False, translate=True, tracking=True)
    product_id = fields.Many2one(comodel_name="product.product", string="Product", tracking=True, ondelete="restrict")
    price = fields.Float(string="Hour Price", required=False, tracking=True)
    capsule_ids = fields.One2many(comodel_name="capsule", inverse_name="service_id", string="Capsules",
                                  required=False, )
    active = fields.Boolean(string='Active', default=True, tracking=True,
                            help="If unchecked, it will allow you to hide the record without deleting it.")

    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)
    def get_capsule_ids_time_slot(self, branch_id, date_from=None):
        """ Get available time slots for all capsules in the service for a specific branch and date."""
        # branch_id peut être un id (int) ou un record
        branch = branch_id
        if not getattr(branch_id, 'id', None):
            branch = self.env['res.branch'].browse(branch_id)

        target_date = fields.Date.to_date(date_from) if date_from else fields.Date.today()

        capsules = self.capsule_ids.filtered(lambda r: r.branch_id.id == branch.id)
        slots = []
        for capsule in capsules:
            capsule_slots = capsule.get_available_slots(date_from=target_date)
            if capsule_slots:
                slots.append({
                    'capsule_id': capsule.id,
                    'name': capsule.name,
                    'slots': capsule_slots
                })
        return slots


class Capsules(models.Model):
    _name = "capsule"
    _rec_name = "display_name"
    _description = "Capsules Management"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    display_name = fields.Char(compute='_compute_display_name', store=True)
    active = fields.Boolean(string='Active', default=True, tracking=True,
                            help="If unchecked, it will allow you to hide the record without deleting it.")
    service_id = fields.Many2one(comodel_name="capsule.service", string="Service Category", tracking=True,
                                 required=True,
                                 ondelete="restrict")
    product_id = fields.Many2one(comodel_name="product.product", string="Product", tracking=True,
                                 related="service_id.product_id", ondelete="restrict")
    product_tmpl_id = fields.Many2one(comodel_name="product.template", string="Product Template",
                                      related="product_id.product_tmpl_id", store=True, ondelete="restrict")
    name = fields.Char(string="Name", required=True, tracking=True, translate=True, )
    default_hours = fields.Float(string="Default Hours", required=True, tracking=True)
    line_ids = fields.One2many(comodel_name="reservation", inverse_name="capsule_id", string="Reservations",
                               required=False, )
    duration_lock = fields.Float('Edit or Cancel Before', default=15.0, tracking=True)
    lounge_id = fields.Many2one(comodel_name="lms.lounge", string="Lounge", required=True, tracking=True,
                                ondelete="restrict")
    branch_id = fields.Many2one(comodel_name="res.branch", string="Branch", related="lounge_id.branch_id", store=True,
                                ondelete="restrict", tracking=True)
    unavailability_ids = fields.One2many(comodel_name="capsule.unavailability", inverse_name="capsule_id",
                                         string="unavailability", required=False, )

    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)
    @api.depends('service_id','service_id.name', 'name')
    def _compute_display_name(self):
        for rec in self:
            service_name = rec.service_id.name
            rec.display_name = f"{service_name} - {rec.name}" if service_name and rec.name else ""

    def action_open_unavailability_wizard(self):
        """ Open the unavailability wizard for the capsule.
        """
        return {
            'name': 'Capsule Timeslot Hold',
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'capsule.unavailability.wizard',
            'view_id': self.env.ref('reservation.view_capsule_unavailability_wizard_form').id,
            'target': 'new',
            'context': {'default_capsule_id': self.id}
        }

    def get_available_slots(self, date_from=None):
        """ Get available time slots for the capsule on a specific date.
        """
        self.ensure_one()

        local_tz = pytz.timezone('Asia/Riyadh')
        utc_tz = pytz.UTC

        target_date = fields.Date.from_string(date_from) if date_from else fields.Date.today()

        start_naive = datetime.combine(target_date, time.min)
        end_naive = datetime.combine(target_date, time.max)
        start_ksa = local_tz.localize(start_naive)
        end_ksa = local_tz.localize(end_naive)

        start_utc = start_ksa.astimezone(utc_tz)
        end_utc = end_ksa.astimezone(utc_tz)

        def to_aware_utc(dt):
            """ Convert a naive datetime to an aware UTC datetime.
            """
            if dt.tzinfo is None:
                return dt.replace(tzinfo=utc_tz)
            return dt.astimezone(utc_tz)

        now_utc = datetime.utcnow()
        # --- Get confirmed reservations ---
        reservations = self.line_ids.filtered(
            lambda r: r.state == 'confirmed' and
                      r.date_from and r.date_to and
                      to_aware_utc(r.date_from) < end_utc and
                      to_aware_utc(r.date_to) > start_utc and
                      to_aware_utc(r.expire_on) > now_utc
        )
        reserved_slots = []
        for r in reservations:
            res_start_ksa = to_aware_utc(r.date_from).astimezone(local_tz)
            res_end_ksa = to_aware_utc(r.date_to).astimezone(local_tz)
            reserved_slots.append((res_start_ksa, res_end_ksa))

        # --- Get maintenance/inactive periods ---
        inactive_periods = self.env['capsule.unavailability'].sudo().search([
            ('capsule_id', '=', self.id),
            ('date_from', '<', end_utc),
            ('date_to', '>', start_utc)
        ])
        inactive_slots = []
        for period in inactive_periods:
            in_start_ksa = to_aware_utc(period.date_from).astimezone(local_tz)
            in_end_ksa = to_aware_utc(period.date_to).astimezone(local_tz)
            inactive_slots.append((in_start_ksa, in_end_ksa))

        # --- Build full day slot list ---
        slots = []
        slot_id = 1
        current_time = start_ksa
        while current_time < end_ksa:
            next_time = current_time + timedelta(hours=1)
            if next_time > end_ksa:
                next_time = end_ksa

            # Reservation check
            available = True
            for res_start, res_end in reserved_slots + inactive_slots:
                if current_time < res_end and next_time > res_start:
                    available = False
                    break

            slots.append({
                "id": slot_id,
                "start": current_time.strftime("%H:%M"),
                "end": next_time.strftime("%H:%M"),
                "available": available  # Available for use or under maintenance
            })

            slot_id += 1
            current_time = next_time

        return slots

    def check_capsule_availability(self, branch_id=None, date_from=None, date_to=None, max_slots_per_list=6,
                                   timezone=None, api=None):
        """ Check capsule availability and return available time slots."""
        slots = []
        current_time = fields.Datetime.now()

        # Set date_from to the start of the day or current time if not provided
        if not date_from:
            date_from = start_of(fields.Datetime.now(), 'day')
        else:
            date_from = fields.Datetime.to_datetime(date_from) if not isinstance(date_from,
                                                                                 fields.Datetime) else date_from

        # Set date_to to the end of the day if not provided
        if not date_to:
            date_to = end_of(date_from, 'day')
        else:
            date_to = fields.Datetime.to_datetime(date_to) if not isinstance(date_to, fields.Datetime) else date_to
        now_utc = datetime.utcnow()

        # Fetch all reservations for the capsule within the given date range
        reservations = self.env['reservation'].search([
            ('capsule_id', '=', self.id),
            ('branch_id', '=', branch_id),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
            ('expire_on', '>', now_utc),
        ], order='date_from')

        last_end_time = date_from
        default_hours_delta = timedelta(hours=self.default_hours)

        if not reservations and date_from.date() == current_time.date():

            slots.append(_prepare_slot(start_of(current_time, 'day'), current_time, current_time, available=False))
            slots.append(_prepare_slot(current_time, end_of(current_time, 'day'), current_time, available=True))
        else:
            for reservation in reservations:
                reserved_from = fields.Datetime.from_string(reservation.date_from) if not isinstance(
                    reservation.date_from, fields.Datetime) else reservation.date_from
                reserved_to = fields.Datetime.from_string(reservation.date_to) if not isinstance(reservation.date_to,
                                                                                                 fields.Datetime) else reservation.date_to

                # Check for available slots before the current reservation
                if last_end_time < reserved_from:
                    gap_duration = reserved_from - last_end_time
                    if gap_duration >= default_hours_delta:
                        slots.append(_prepare_slot(last_end_time, reserved_from, current_time, available=True,
                                                   reservation_id=reservation))
                # else:
                # Add the current reservation slot as not available
                slots.append(_prepare_slot(reserved_from, reserved_to, current_time, available=False,
                                           reservation_id=reservation))

                last_end_time = reserved_to
            # Check for available slots after the last reservation until the end of the day
            if last_end_time < date_to:
                gap_duration = date_to - last_end_time
                if gap_duration >= default_hours_delta:
                    slots.append(_prepare_slot(last_end_time, date_to, current_time, available=True))
        if api:
            return slots

        # Split slots into sublists of maximum length
        slots_sublists = split_into_sublists(slots, max_length=max_slots_per_list)
        # print(slots_sublists)
        return {
            'slots': slots_sublists
        }

    def is_capsule_available(self, date_from, date_to, branch_id=None):
        """
        Check if the capsule is available between date_from and date_to.
        Returns True if available, False otherwise.
        """
        now_utc = datetime.utcnow()

        # Fetch all reservations for the capsule within the given time frame
        conflicting_reservations = self.env['reservation'].search([
            ('capsule_id', '=', self.id),
            ('date_from', '<', date_to),
            ('expire_on', '>', now_utc),
            ('date_to', '>', date_from),
        ])
        # If there are no conflicting reservations, the capsule is available
        return len(conflicting_reservations) == 0

    def data_available(self, date_from, date_to):
        """
        Check if the capsule is available between date_from and date_to.
        Returns True if available, False otherwise.
        """
        # Fetch all reservations for the capsule within the given time frame
        now_utc = datetime.utcnow()

        conflicting_reservations = self.env['reservation'].search([
            ('capsule_id', '=', self.id),
            ('date_from', '<', date_to),
            ('expire_on', '>', now_utc),
            ('date_to', '>', date_from),
        ])

        # If there are no conflicting reservations, the capsule is available
        return conflicting_reservations.read()

    def find_alternative_capsules(self, date_from, date_to, branch_id=None):
        """
        Find alternative Capsules that are available between date_from and date_to.
        """
        # Check if the current capsule is available
        if self.is_capsule_available(date_from, date_to, branch_id):
            return {
                'status': 'available',
                'capsule_id': self.id,
                'message': f"Capsule {self.name} is available from {date_from} to {date_to}."
            }

        # If not available, find other capsules that are available
        available_capsules = []
        capsules = self.env['capsule'].search([('id', '!=', self.id)])  # Exclude the current capsule

        for capsule in capsules:
            if capsule.is_capsule_available(date_from, date_to, branch_id):
                available_capsules.append({
                    'capsule_id': capsule.id,
                    'name': capsule.name,
                    'reservation': [],
                    'message': f"Capsule {capsule.name} is available from {date_from} to {date_to}."
                })

        if available_capsules:
            return {
                'status': 'not_available',
                'capsule_id': self.id,
                'reservation': self.data_available(date_from, date_to),
                'message': f"capsule {self.name} is not available from {date_from} to {date_to}.",
                'alternatives': available_capsules
            }
        else:
            return {
                'status': 'not_available',
                'capsule_id': self.id,
                'reservation': self.data_available(date_from, date_to),
                'message': f"No Capsules are available from {date_from} to {date_to}."
            }

    def open_reservations_action(self):
        """ Open the reservations related to this capsule.
        """
        self.ensure_one()
        return {
            'name': 'Reservations',
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'list,form',
            'res_model': 'reservation',
            'domain': [('capsule_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }


class CapsuleUnavailability(models.Model):
    _name = "capsule.unavailability"
    _description = "Capsules Timeslot Hold"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    capsule_id = fields.Many2one("capsule", string="Capsule", required=True, ondelete="restrict", tracking=True)
    date_from = fields.Datetime(string="From", required=True, tracking=True)
    date_to = fields.Datetime(string="To", required=True, tracking=True)
    reason = fields.Char(string="Reason", help="Reason for marking the Capsule unavailable, e.g., maintenance", tracking=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_to <= rec.date_from:
                raise ValueError("End date must be after start date.")


class CapsuleUnavailabilityWizard(models.TransientModel):
    _name = 'capsule.unavailability.wizard'
    _description = 'Capsules Timeslot Hold Wizard'

    capsule_id = fields.Many2one('capsule', string='Capsule', required=True, readonly=True, ondelete="restrict")
    date_from = fields.Datetime(string='From', required=True)
    date_to = fields.Datetime(string='To', required=True)
    reason = fields.Char(string='Reason', required=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_to <= rec.date_from:
                raise ValueError("End date must be after start date.")

    def action_confirm(self):
        """ Create the unavailability record """
        self.ensure_one()
        self.env['capsule.unavailability'].create({
            'capsule_id': self.capsule_id.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'reason': self.reason,
        })
        return {'type': 'ir.actions.act_window_close'}
