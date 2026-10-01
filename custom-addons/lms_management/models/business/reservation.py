import logging
import requests
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.tools.date_utils import add, subtract
from odoo.exceptions import UserError

# Logger for SMS and reservation actions
_logger = logging.getLogger(__name__)


class Reservation(models.Model):
    _name = "reservation"
    _rec_name = "sequence"
    _inherit = ['mail.thread']
    _description = "Reservation Management"
    _order = "id desc"

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to assign a sequence number immediately.
        """
        records = super(Reservation, self).create(vals_list)
        for record in records:
            next_seq = self.env['ir.sequence'].next_by_code('reservation.sequence')
            record.sequence = next_seq
            _logger.info("Assigned sequence %s to reservation %s", next_seq, record.id)
        return records

    # --- Fields ---
    sequence = fields.Char(string='Sequence', readonly=True, copy=False, index=True, default=lambda self: 'Draft')
    active = fields.Boolean(default=True, tracking=True)
    partner_id = fields.Many2one(comodel_name="res.partner", string="Partner", required=False, ondelete="restrict",
                                 tracking=True)
    customer = fields.Char(string="Customer", required=True, tracking=True)
    phone = fields.Char(string="Phone", required=True, tracking=True)
    email = fields.Char(string="Email", tracking=True)
    capsule_id = fields.Many2one(comodel_name="capsule", string="Capsule", ondelete="restrict", tracking=True)
    product_id = fields.Many2one(comodel_name="product.product", string="Product", related="capsule_id.product_id",
                                 store=True, required=True, ondelete="restrict", tracking=True)
    date_from = fields.Datetime(string="From", tracking=True)
    date_to = fields.Datetime(string="To", tracking=True)
    hours = fields.Float(string="Hours", tracking=True)
    state = fields.Selection(
        [('confirmed', 'Confirmed'), ('running', 'Running'), ('expired', 'Expired'), ('cancelled', 'Cancelled')],
        string="State", compute='get_state', store=True, tracking=True)
    lounge_id = fields.Many2one(comodel_name="lms.lounge", string="Lounge", required=True, tracking=True,
                                related="capsule_id.lounge_id", store=True, ondelete="restrict")
    branch_id = fields.Many2one(comodel_name="res.branch", string="Branch", related="lounge_id.branch_id", store=True,
                                ondelete="restrict", tracking=True)
    expire_on = fields.Datetime(string="Expire On", required=False, tracking=True)
    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company, tracking=True)
    def action_cancel(self):
        """Cancel the reservation and set state to 'cancelled'. """
        for rec in self:
            rec.state = 'cancelled'
            _logger.info("Reservation %s cancelled", rec.id)

    @api.depends('date_from', 'date_to')
    def get_state(self):
        """Compute whether the reservation is confirmed, running, or expired."""
        now = fields.Datetime.now()
        for rec in self:
            if rec.date_from and rec.date_to:
                if rec.date_to < now:
                    rec.state = 'expired'
                elif rec.date_from < now < rec.date_to:
                    rec.state = 'running'
                else:
                    rec.state = 'confirmed'
            else:
                rec.state = 'confirmed'

    @api.model
    def create_reservation(self, vals):
        """RPC method called from JS to create or update a reservation,
        then send confirmation SMS using user's timezone."""
        _logger.info("create_reservation called with vals=%s", vals)
        capsule_id = vals['capsule_id']
        time_str_input = vals['date_from']
        date_to_input = vals.get('date_to')
        product_id = vals.get('product_id')
        phone = vals.get('phone')
        reservation_id = vals.get('reservation_id')
        edit = vals.get('edit', False)
        default_hours = int(vals.get('number', 1))

        capsule = self.env['capsule'].browse(capsule_id)
        # Build naive datetime from input time string
        today = datetime.today()
        time_mask = datetime.strptime(time_str_input, "%H:%M").time()
        date_from = datetime.combine(today, time_mask)

        if date_to_input:
            mask_to = datetime.strptime(date_to_input, "%H:%M").time()
            date_to = datetime.combine(today, mask_to)
        else:
            date_to = date_from + timedelta(hours=default_hours)

        # Check availability in UTC by subtracting offset
        availability = capsule.find_alternative_capsules(
            subtract(date_from, hours=3),
            subtract(date_to, hours=3))
        availability['data'] = []

        if availability.get('status') == 'available':
            _logger.info("capsule %s available, proceeding to create/update reservation", capsule_id)
            record_vals = {
                'capsule_id': capsule_id,
                'date_from': subtract(date_from, hours=3),
                'date_to': subtract(date_to, hours=3),
                'phone': phone,
                'product_id': product_id,
                'customer': vals['name'],
                'hours': vals['number'],
            }
            if edit and reservation_id:
                reservation = self.browse(reservation_id)
                reservation.write(record_vals)
                _logger.info("Updated reservation %s", reservation.id)
            else:
                reservation = self.create(record_vals)
                _logger.info("Created reservation %s", reservation.id)

            # Format SMS datetime in user's timezone
            local_dt = fields.Datetime.context_timestamp(self, reservation.date_from)
            date_str = local_dt.strftime("%Y-%m-%d")
            time_str = local_dt.strftime("%H:%M")

            msg = (f"أهلًا وسهلًا..\n"
                   f"تم تأكيد حجزكم في حياك لاونج بتاريخ {date_str} الساعة {time_str} للخدمة ({reservation.capsule_id.with_context(lang='ar_001').name}).\n\n"
                   "حياكم الله في تجربة استثنائية تتجاوز التوقعات.\n\n"
                   f"Welcome to Hayyak Lounge,\n"
                   f"Your reservation has been confirmed for the {reservation.capsule_id.name} service on {date_str} at {time_str}.\n"
                   "We look forward to providing you with an exceptional experience that exceeds expectations.")

            _logger.info("About to send confirmation SMS for reservation %s", reservation.id)
            # reservation.send_sms(reservation.phone, msg)
            _logger.info("Confirmation SMS sent for reservation %s", reservation.id)

            availability['data'] = reservation.read()[0]
            availability['reservation_id'] = reservation.id
            return availability
        else:
            _logger.info("Capsule %s not available, returning alternatives", capsule_id)
            return availability

    def _get_config_param(self, param_name, error_msg=None):
        """Helper function to fetch system configuration parameters."""
        param = self.env['ir.config_parameter'].sudo().get_param(param_name)
        if not param and error_msg:
            raise UserError(error_msg)
        return param

    def send_sms(self, phone_number, message):
        """
        Send a single SMS via Taqniyat API.
        """
        _logger.info("Sending SMS to %s: %s", phone_number, message)
        url = self._get_config_param('taqnyat_url',
                                     'Please configure the Taqnyat url in system settings.')
        token = self._get_config_param('taqnyat_token',
                                       'Please configure the Taqnyat API token in system settings.')
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", }
        payload = {"recipients": [phone_number], "body": message, "sender": "HAYYAK", }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            _logger.info("SMS sent successfully, response: %s", resp.text)
        except Exception as e:
            _logger.error("Failed to send SMS to %s: %s", phone_number, e)

    @api.model
    def _cron_send_reservation_reminders(self):
        """
        Cron: runs every minute to send a reminder 10min before reservation start.
        """
        now = fields.Datetime.now()
        in_ten = now + timedelta(minutes=10)
        to_remind = self.search([('date_from', '>=', now), ('date_from', '<=', in_ten), ('state', '=', 'confirmed'), ])
        _logger.info("_cron_send_reservation_reminders found %s to remind", len(to_remind))
        for rec in to_remind:
            local_dt = fields.Datetime.context_timestamp(self, rec.date_from)
            t = local_dt.strftime("%H:%M")
            msg = (
                f"نذكّركم بأن موعد حجزكم للخدمة ({rec.capsule_id.with_context(lang='ar_001').name}) سيبدأ خلال 10 دقائق، في تمام الساعة {t}.\n"
                "فريق حياك لاونج جاهز لاستقبالكم.\n\n"
                f"This is a reminder that your reservation for the '{rec.capsule_id.name}' service will begin in 10 minutes at {t}.\n"
                "The Hayyak Lounge team is ready to welcome you.")

            # rec.send_sms(rec.phone, msg)

    @api.model
    def _cron_send_reservation_surveys(self):
        """Cron: runs every 30min to send a survey after reservation ends."""
        now = fields.Datetime.now()
        ended = self.search([('date_to', '>=', now - timedelta(hours=1)), ('date_to', '<=', now),
                             ('state', 'in', ('running', 'expired')), ])
        _logger.info("_cron_send_reservation_surveys found %s ended reservations", len(ended))
        survey_link = "https://yourdomain.com/e-survey"
        for rec in ended:
            local_dt = fields.Datetime.context_timestamp(self, rec.date_to)
            date_str = local_dt.strftime("%Y-%m-%d")
            t = local_dt.strftime("%H:%M")
            msg = (
                f"شكرًا لاستخدامكم خدمة ({rec.capsule_id.service_id.with_context(lang='ar_001').name}) بتاريخ {date_str} الساعة {t}.\n"
                f"يرجى تقييم تجربتكم: {survey_link}\n\n"
                f"Thank you for using '{rec.capsule_id.service_id.name}' on {date_str} at {t}.\n"
                f"Please rate your experience: {survey_link}")

            # rec.send_sms(rec.phone, msg)
