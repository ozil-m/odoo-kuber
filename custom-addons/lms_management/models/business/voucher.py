# -*- coding: utf-8 -*-
import os
from io import BytesIO
from datetime import timedelta, datetime
import logging
import requests

_logger = logging.getLogger(__name__)
try:
    import qrcode
except ImportError:
    qrcode = None
try:
    import base64
except ImportError:
    base64 = None
from odoo import models, fields, api, _
from odoo.exceptions import UserError


def _prepare_invoice_bulk_lines(bookings_to_process):
    """
    Prepare the invoice line values from the given bookings.
    This method is used to create invoice lines from multiple bookings.
    """
    invoice_lines = []

    for booking in bookings_to_process:
        analytic_account_id = booking.branch_id.payment_analtic_id.id or False
        department_id = booking.branch_id.department_id.id or False

        # Add booking lines if present
        for line in booking.line_ids:
            invoice_lines.append((0, 0, {
                'name': line.capsule_id.name or line.product_id.name or _('Unnamed Product'),
                'quantity': line.hours,
                'price_unit': line.net_price,
                'analytic_account_id': analytic_account_id,
                'department_id': department_id,
                'tax_ids': [(6, 0, line.tax_id.ids)],
            }))

        # Add booking main product line
        invoice_lines.append((0, 0, {
            'name': booking.product_id.name,
            'quantity': booking.quantity,
            'price_unit': booking.net_price,
            'tax_ids': [(6, 0, booking.tax_id.ids)],
            'company_id': booking.company_id.id,
            'analytic_account_id': analytic_account_id,
            'department_id': department_id,
        }))

    return invoice_lines


class LoungeElectronicVoucher(models.Model):
    _name = 'lounge.voucher'
    _rec_name = 'sequence'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Lounge Electronic Voucher"
    _order = "id desc"

    sequence = fields.Char(string='Voucher #', readonly=True, copy=False, index=True, default=lambda self: 'Draft',
                           help="Sequence identifier for the voucher.", tracking=True)
    state = fields.Selection(string="State",
                             selection=[('draft', 'Draft'), ('issued', 'Issued'), ('accepted', 'Accepted'),
                                        ('canceled', 'Canceled')], default='draft', tracking=True)
    company_id = fields.Many2one(comodel_name="res.company", string="Company", readonly=True,
                                 default=lambda self: self.env.company)
    client_id = fields.Many2one(comodel_name="res.partner", string="Client", required=True,
                                default=lambda self: self.env.user.partner_id.parent_id.id, readonly=False,
                                ondelete="restrict")
    partner_id = fields.Many2one('res.partner', string="Customer ID", ondelete="restrict", tracking=True)
    partner = fields.Char(string='Customer Name', required=True, tracking=True)
    email = fields.Char(string='Email', required=False, tracking=True)
    mobile = fields.Char(string='Mobile Number', required=False, tracking=True)
    flight_number = fields.Char(string='Flight Number', tracking=True)
    origin = fields.Char(string='Origin', tracking=True)
    destination = fields.Char(string='Destination', tracking=True)
    departure_date = fields.Datetime(string="Departure Date", tracking=True)
    boarding = fields.Text('Boarding Pass', tracking=True)
    qr_code = fields.Binary('QR Code', copy=False)
    end_img = fields.Binary(compute='_compute_end_img', string='End Image', store=False)
    used_on = fields.Datetime(string="Used On", tracking=True)
    lounge_id = fields.Many2one('lms.lounge', string='lounge', ondelete="restrict", tracking=True)
    branch_id = fields.Many2one('res.branch', string='Branch', related='lounge_id.branch_id', store=True, readonly=True,
                                ondelete="restrict", tracking=True)
    product_id = fields.Many2one('product.product', 'Product', ondelete="restrict", tracking=True)
    quantity = fields.Integer(string="Quantity", default=1, tracking=True)
    used_quantity = fields.Integer(string="Used Quantity", tracking=True)
    remain_quantity = fields.Integer(string="Remaining Quantity", compute='_compute_remain_quantity', store=True)
    source = fields.Char(string="Source", required=False, tracking=True)
    line_ids = fields.One2many(comodel_name='voucher.line', inverse_name='voucher_id', string='Voucher Lines',
                               help='Lines of the voucher, each line can be a reservation or a product.', )
    price = fields.Float(string="Gross Price", required=False, tracking=True, )
    discount_amount = fields.Float(string="Discount", required=False, tracking=True)
    net_price = fields.Float(string="Net Price", required=False, tracking=True)
    total_excluded = fields.Float(string="Total Excluded", required=False, compute='_compute_amounts', store=True,
                                  tracking=True)
    amount_tax = fields.Float(string="Tax Amount", required=False, compute='_compute_amounts', store=True,
                              tracking=True)
    total_included = fields.Float(string="Total Included", required=False, compute='_compute_amounts', store=True,
                                  tracking=True)
    tax_id = fields.Many2many('account.tax', string='Taxes', context={'active_test': False}, ondelete="restrict",
                              tracking=True)
    invoice_id = fields.Many2one(comodel_name="account.move", string="Invoice", required=False, tracking=True,
                                 ondelete="restrict")
    note = fields.Char(string="Note", required=False, tracking=True, )
    hayyak_app = fields.Boolean(string="Hayyak APP", tracking=True)
    sc_json = fields.Char(string="SkyCentral Json", required=False, )
    sky_central_ref = fields.Char(string="SkyCentral Ref", required=False, )
    membership_tier_id = fields.Char(string="membershipTierId", required=False, )
    moyasar_payment_ref = fields.Char(string="Moyasar Payment Ref", required=False, tracking=True)
    segment_id = fields.Char(string="segmentId", required=False, tracking=True)

    def send_sms(self, phone_number, message):
        """Send a single SMS via Taqniyat API. """
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

    def notify_admin(self, note):
        """Helper function to notify managers via email and activity."""
        group = self.env.ref('base.group_system')
        users = group.users
        for user in users:
            # Create an activity
            self.env['mail.activity'].create({
                'res_model_id': self.env['ir.model']._get('lounge.voucher').id,
                'res_id': self.id,
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,  # Set activity type to 'To Do'
                'summary': 'Somthing went wrong',
                'note': note,
                'date_deadline': fields.Date.today(),
                'user_id': user.id,
            })

    @api.depends('quantity', 'used_quantity')
    def _compute_remain_quantity(self):
        """Compute remaining quantity = quantity - used_quantity (never below 0)."""
        for rec in self:
            q = rec.quantity or 0
            u = rec.used_quantity or 0
            rec.remain_quantity = max(q - u, 0)

    def _get_config_param(self, param_name, error_msg=None):
        """Fetch a system configuration parameter or raise an error if missing."""
        param = self.env['ir.config_parameter'].sudo().get_param(param_name)
        if not param and error_msg:
            raise UserError(error_msg)
        return param

    def _get_or_create_partner(self, name=None, email=None, mobile=None):
        """
        Find an existing partner by email or name, otherwise create a new one.
        Used to ensure every voucher is linked to a valid partner.
        """
        Partner = self.env['res.partner'].with_context(voucher_autocreate=True).sudo()

        partner = False
        if email:
            partner = Partner.search([('email', '=', email)], limit=1)
        if not partner and name:
            partner = Partner.search([('name', '=', name)], limit=1)
        if not partner:
            vals = {'name': name or _('Guest')}
            if email:
                vals['email'] = email
            if mobile:
                vals.update({'mobile': mobile, 'phone': mobile})
            partner = Partner.create(vals)
        return partner

    def _sync_customer_fields(self, vals):
        """Ensure customer-related fields (client_id, partner_id, partner name) are properly set."""
        client_id = vals.get('client_id')
        if not client_id:
            name = vals.get('partner') or self.partner
            email = vals.get('email') or self.email
            mobile = vals.get('mobile') or self.mobile
            if name or email or mobile:
                partner = self._get_or_create_partner(name=name, email=email, mobile=mobile)
                vals['client_id'] = partner.id
                client_id = partner.id

        if not vals.get('partner_id') and client_id:
            vals['partner_id'] = client_id

        if not vals.get('partner'):
            pid = vals.get('partner_id') or self.partner_id.id
            if pid:
                partner_name = self.env['res.partner'].sudo().browse(pid).name
                if partner_name:
                    vals['partner'] = partner_name
        return vals

    # ---------------- ORM overrides ----------------
    @api.model_create_multi
    def create(self, vals):
        """Ensure product_id and customer fields are set when creating a voucher."""
        for record_vals in vals:
            if not record_vals.get('source'):
                record_vals['source'] = "Manual"
            if not record_vals.get('product_id'):
                product_id = self._get_config_param('voucher_product_id',
                                                    _("Default voucher product ID is not set in system configuration."))
                record_vals['product_id'] = int(product_id) if product_id else False
                record_vals['tax_id'] = self.env['product.product'].browse(int(product_id)).taxes_id.filtered(
                    lambda t: t.company_id == self.env.company).ids if product_id else False
        return super(LoungeElectronicVoucher, self).create(vals)

    @api.depends()
    def _compute_end_img(self):
        """Load end image from static resources."""
        module_path = os.path.dirname(os.path.abspath(__file__))
        img_path = os.path.join(module_path, '..', 'static', 'src', 'end.jpg')
        for rec in self:
            try:
                with open(img_path, 'rb') as f:
                    rec.end_img = base64.b64encode(f.read())
            except Exception as e:
                _logger.error("Error loading end image: %s", str(e))
                rec.end_img = False

    def _generate_qr(self):
        """Generate and attach a QR code image for the voucher sequence."""
        for rec in self:
            if qrcode and base64:
                qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=3, border=4, )
                qr.add_data(rec.sequence or '')
                qr.make(fit=True)
                img = qr.make_image()
                temp = BytesIO()
                img.save(temp, format="PNG")
                qr_image = base64.b64encode(temp.getvalue())
                rec.sudo().update({'qr_code': qr_image})
            else:
                raise UserError(_('Necessary requirements to generate QR Code are not satisfied.'))

    def send_email(self):
        """ Send an email with the voucher PDF attached.
        The email will be sent to the client with a request to verify the voucher details.
        """
        for order in self:
            IrMailServer = self.env['ir.mail_server']
            mail_servers = IrMailServer.sudo().search([], limit=1)
            if not mail_servers:
                continue
            email_subject = "Voucher No.%s" % (order.sequence or '')
            template_id = order.env.ref('lms_management.lounge_electronic_voucher_email_template')
            report_xml_id = 'lms_management.action_print_voucher'
            report = order.env.ref(report_xml_id)
            if report:
                pdf_data = report._render_qweb_pdf(report_ref=report_xml_id, res_ids=order.ids)
                data_record = base64.b64encode(pdf_data[0])
                try:
                    attachment = order.env['ir.attachment'].create({
                        'name': 'Voucher - %s.pdf' % (order.sequence or ''),
                        'type': 'binary',
                        'datas': data_record,
                        'res_model': 'lounge.voucher',
                        'res_id': order.id,
                        'public': True,
                        'mimetype': 'application/pdf'
                    })
                except Exception as e:
                    raise UserError(f" Somthing went wrong while attaching the voucher:\n {str(e)}")
                email_values = {
                    'subject': email_subject,
                    'email_from': order.company_id.email_formatted or '',
                    'email_to': order.email,
                    'auto_delete': False,
                    'message_type': 'email',
                    'recipient_ids': [],
                    'partner_ids': [],
                    'scheduled_date': False,
                    'attachment_ids': [(6, 0, [attachment.id])],
                }
                try:
                    template_id.sudo().send_mail(order.id, force_send=True, raise_exception=True,
                                                 email_values=email_values)
                except Exception as e:
                    raise UserError(f" Somthing went wrong while sending the email:\n {str(e)}")

    def action_confirm(self):
        """Issue the voucher: require a client, generate sequence, QR, and send by email."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Voucher must be in draft state to confirm.'))

            if not rec.client_id:
                raise UserError(_('A customer (Client) must be set before issuing the voucher.'))
            if not rec.partner_id:
                rec.partner_id = rec.client_id.id
            if not rec.partner:
                rec.partner = rec.client_id.name

            seq = rec.env['ir.sequence'].sudo().next_by_code('lounge.voucher.sequence')
            rec.sequence = seq
            rec.state = 'issued'
            rec._generate_qr()
            if rec.email:
                rec.send_email()

    def action_use(self, qty=1, lounge_id=None):
        """Consume qty units of the voucher (multi-guest support)."""
        for rec in self:
            if rec.state != 'issued':
                raise UserError(_('Only issued vouchers can be used.'))

            if rec.used_quantity >= rec.quantity:
                raise UserError(_('This voucher has already been fully used.'))

            new_used = rec.used_quantity + int(qty or 1)
            if new_used > rec.quantity:
                raise UserError(_('Cannot use more than the available voucher quantity.'))

            rec.used_quantity = new_used
            rec.used_on = fields.Datetime.now()
            if lounge_id:
                rec.lounge_id = lounge_id

            if rec.used_quantity >= rec.quantity:
                rec.state = 'accepted'

    def action_accepted(self, lounge_id=None):
        """Force voucher into accepted state (manually)."""
        for rec in self:
            rec.state = 'accepted'
            rec.used_on = fields.Datetime.now()
            if lounge_id:
                rec.lounge_id = lounge_id

    def action_cancel(self):
        """ Cancel the voucher if in draft or issued state, also cancel linked lines."""
        for rec in self:
            if rec.state not in ['draft', 'issued']:
                raise UserError(_('Voucher can only be canceled in draft or issued state.'))
            if rec.line_ids:
                rec.line_ids.action_cancel()
            rec.state = 'canceled'

    @api.depends('line_ids.total_included', 'net_price', 'tax_id')
    def _compute_amounts(self):
        """
        Compute the total price of the voucher by summing the net_prices of all lines.
        """
        for voucher in self:
            total_excluded = 0.0
            total_included = 0.0
            amount_tax = 0.0
            if voucher.tax_id and voucher.hayyak_app:
                amount_tax_vals = voucher.tax_id[0].compute_all(price_unit=voucher.net_price, currency=False,
                                                                quantity=voucher.quantity,
                                                                product=voucher.product_id,
                                                                partner=voucher.partner_id)
                if amount_tax_vals:
                    total_excluded = amount_tax_vals.get('total_excluded') + sum(
                        line.total_excluded for line in voucher.line_ids)
                    total_included = amount_tax_vals.get('total_included') + sum(
                        line.total_included for line in voucher.line_ids)
                    amount_tax = total_included - total_excluded
            voucher.write({
                'total_excluded': total_excluded,
                'amount_tax': amount_tax,
                'total_included': total_included,
            })

    def _prepare_invoice_line(self):
        """
        Prepare the invoice line values for the voucher.
        This method is used to create invoice lines from the voucher.
        """

        self.ensure_one()
        invoice_lines = []
        analytic_account_id = self.branch_id.payment_analtic_id.id or False
        department_id = self.branch_id.department_id.id or False
        # Add voucher lines if present
        for line in self.line_ids:
            invoice_lines.append((0, 0, {
                'name': line.capsule_id.name or line.product_id.name or _('Unnamed Product'),
                'quantity': line.hours,
                'price_unit': line.net_price,
                'analytic_account_id': analytic_account_id,
                'department_id': department_id,
                'tax_ids': [(6, 0, line.tax_id.ids)],
            }))

        # Add voucher product line
        invoice_lines.append((0, 0, {
            'name': self.product_id.name,
            'quantity': self.quantity,
            'price_unit': self.net_price,
            'tax_ids': [(6, 0, self.product_id.taxes_id.ids)],
            'company_id': self.company_id.id,
            'analytic_account_id': analytic_account_id,
            'department_id': department_id,
        }))
        return invoice_lines

    def send_einvoice_email(self):
        """ Send an email with the invoice attached.
        """
        for order in self:
            email_subject = f"Invoice for Order Number {order.invoice_id.name}فاتورة للطلب رقم "
            template_id = order.env.ref('einvoice.main_standard_invoice_id')
            report_xml_id = 'einvoice.stander_invoice_id'
            report = order.env.ref(report_xml_id)
            if report:
                pdf_data = report._render_qweb_pdf(order.id)
                data_record = base64.b64encode(pdf_data[0])
                attachment = order.env['ir.attachment'].create({
                    'name': 'Invoice - %s.pdf' % (order.sequence or ''),
                    'type': 'binary',
                    'datas': data_record,
                    'public': True,
                    'res_model': 'lounge.voucher',
                    'res_id': order.id,
                    'mimetype': 'application/pdf'
                })
                if order.email:
                    email_values = {
                        'subject': email_subject,
                        'email_from': order.company_id.email_formatted or '',
                        'email_to': order.email,
                        'auto_delete': False,
                        'message_type': 'email',
                        'recipient_ids': [],
                        'partner_ids': [],
                        'scheduled_date': False,
                        'attachment_ids': [(6, 0, [attachment.id])],
                        'body_html': f"""
                                    <div style="background-color:#EFEFEF;padding:20px;border-radius:10px;">
                                      <p style="color:#4A4A4A;font-size:18px;font-weight:bold;">Dear {order.partner or ''},</p>
                                      <p style="color:#4A4A4A;font-size:16px;">
                                       Thank your for your order, please check the invoice attached to this email.
                                      </p>
                                      <br/><br/>
                                      <p style="color:#4A4A4A;font-size:16px;">Best regards,</p>
                                      <p style="color:#4A4A4A;font-size:16px;font-style:italic;"><b>Al Khalejiah Catering</b></p>
                                    </div>
                                """

                    }
                    template_id.sudo().send_mail(order.id, force_send=True, raise_exception=True,
                                                 email_values=email_values)

    def action_create_bulk_invoice(self, bookings_to_process):
        """
        Create an invoice for the voucher.
        Includes voucher lines (if any) and the main product line.
        """

        partner_id = bookings_to_process[0].partner_id
        company_id = bookings_to_process[0].company_id
        invoice_line_ids = _prepare_invoice_bulk_lines(bookings_to_process)

        invoice_vals = {
            'partner_id': partner_id.id,
            'invoice_date': datetime.today().date(),
            'invoice_line_ids': invoice_line_ids,
            'company_id': company_id.id,
            # 'branch_id': self.branch_id.id,
            'move_type': 'out_invoice',
        }
        invoice = self.env['account.move'].sudo().create(invoice_vals)
        self.invoice_id = invoice.id
        invoice.action_post()
        return invoice

    def action_create_invoice(self):
        """
        Create an invoice for the voucher.
        Includes voucher lines (if any) and the main product line.
        """
        self.ensure_one()
        if self.invoice_id:
            raise UserError(_("An invoice has already been created for this voucher."))

        if not self.partner_id:
            raise UserError(_("A customer must be selected before creating an invoice."))

        if not self.product_id:
            raise UserError(_("The voucher product must be selected before creating an invoice."))

        invoice_vals = {
            'partner_id': self.partner_id.id,
            'invoice_date': datetime.today().date(),
            'invoice_line_ids': self._prepare_invoice_line(),
            'company_id': self.company_id.id,
            'branch_id': self.branch_id.id,
            'move_type': 'out_invoice',
        }

        invoice = self.env['account.move'].create(invoice_vals)
        self.invoice_id = invoice.id
        invoice.action_post()
        return invoice

    def action_create_reservations(self):
        """
        Create a reservation from the voucher.
        This method is called when the user wants to create a reservation from the voucher.
        """
        self.ensure_one()
        if not self.hayyak_app or not self.line_ids:
            return True

        for line in self.line_ids:
            if not line.reservation_id:
                line.action_create_reservation()

        return True

    def get_lines_tax_id(self):
        """ Set the tax_id for each line based on the product_id of the capsule.
        This method is called when the voucher is created or updated.
        """
        for voucher in self:
            for line in voucher.line_ids:
                line.get_tax_id()

    def get_reservations(self):
        """ This method returns an action to view related invoices.
        """
        reservations_ids = self.line_ids.mapped('reservation_id.id')

        return {
            'name': 'Reservations',
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'reservation',
            'domain': [('id', 'in', reservations_ids)],
            'context': {
                'create': False,
                'edit': False,
                'hide_buttons': True,  # Custom handling to hide all buttons
            },
        }

    def action_create_payment(self, ):
        """ Function to create a payment for the task.
        """
        for rec in self:
            try:
                amount = rec.invoice_id.amount_total_signed
                moyasar_journal_id = self._get_config_param('moyasar_journal_id',
                                                            _('Please configure Moyasar Journal in the system parameters.'))
                moyasar_journal = self.env['account.journal'].browse(int(moyasar_journal_id))
                if not moyasar_journal.exists():
                    moyasar_journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
                    rec.notify_admin(
                        "moyasar_journal not found , using {moyasar_journal.name} journal*************** id {moyasar_journal.id}")

                label = f'Payment {rec.moyasar_payment_ref} for Booking #{rec.sequence}'

                vals = {
                    "journal_id": moyasar_journal.id,
                    "payment_type": 'inbound',
                    "partner_type": 'customer',
                    "ref": label,
                    "amount": float(amount),
                    "partner_id": rec.partner_id.id,
                    "company_id": rec.company_id.id or rec.env.company.id,

                }
                payment = self.env['account.payment'].sudo().with_context(company_id=rec.company_id.id).create(vals)
                for line in payment.move_id.line_ids:
                    line.sudo().write(
                        {'analytic_account_id': rec.branch_id.payment_analtic_id.id,
                         'department_id': rec.branch_id.department_id.id, })
                payment.action_post()
                invoice = rec.invoice_id
                if invoice.state != 'posted':
                    invoice.action_post()
                if invoice.payment_state == 'paid':
                    return True
                account_to_reconcile = invoice.line_ids.filtered(
                    lambda line: line.account_id.user_type_id.type in ('receivable', 'payable')).mapped('account_id')

                # Get move lines from the invoice and payment
                invoice_move_lines = invoice.line_ids.filtered(lambda line: line.account_id in account_to_reconcile)
                payment_move_lines = payment.line_ids.filtered(lambda line: line.account_id in account_to_reconcile)

                # Combine the move lines to reconcile
                move_lines_to_reconcile = invoice_move_lines + payment_move_lines

                # Reconcile the move lines
                move_lines_to_reconcile.reconcile()

                return True
            except Exception as e:
                message = f'Payment Issue: \n' + str(e)
                # rec.sudo().notify_admin_for_failed_payments(message)
                _logger.info("Error in processing Moyasar payment callback: %s", str(e))
                return True
        return True


class VoucherLine(models.Model):
    _name = 'voucher.line'
    _description = 'Voucher Line'

    voucher_id = fields.Many2one(comodel_name='lounge.voucher', string='Voucher', required=False, ondelete="cascade")
    capsule_id = fields.Many2one(comodel_name='capsule', string='Capsule', required=False, ondelete="restrict")
    product_id = fields.Many2one(comodel_name="product.product", string="Product", related='capsule_id.product_id',
                                 ondelete="restrict")
    reservation_id = fields.Many2one(comodel_name='reservation', string='Reservation', required=False,
                                     ondelete="restrict")
    date_from = fields.Datetime(string="From", required=True, )
    hours = fields.Integer(string="Hours", required=True, )
    date_to = fields.Datetime(string="To", compute='_compute_date_to', store=True, )
    price_unit = fields.Float(string="Hour Price", required=False)
    discount_amount = fields.Float(string="Discount", required=False)
    net_price = fields.Float(string="Net Price", required=False)
    total_excluded = fields.Float(string="Total Excluded", compute='_compute_amounts', store=True, )
    amount_tax = fields.Float(string="Tax Amount", compute='_compute_amounts', store=True, )
    total_included = fields.Float(string="Total Included", compute='_compute_amounts', store=True, )
    company_id = fields.Many2one(related='voucher_id.company_id', string='Company', store=True, index=True)
    tax_id = fields.Many2many('account.tax', string='Taxes', context={'active_test': False}, ondelete="restrict")
    note = fields.Char(string="Note", required=False, )

    def action_cancel(self):
        """Cancel the reservation and set state to 'cancelled'."""
        for rec in self:
            rec.reservation_id.action_cancel()

    def unlink(self):
        """Override unlink to also delete the associated reservation if it exists
        and is in the 'confirmed' state."""
        for line in self:
            reservation = line.reservation_id
            if reservation and reservation.state not in ['confirmed']:
                raise UserError(_(
                    "You cannot delete a voucher line linked to a reservation unless "
                    "it is in the 'confirmed' state. Current state: '%s'.") % reservation.state)
            reservation.unlink()
        return super(VoucherLine, self).unlink()

    def get_tax_id(self):
        """ Set the tax_id based on the product_id of the capsule."""
        for rec in self:
            rec.tax_id = rec.product_id.taxes_id.filtered(
                lambda t: t.company_id == rec.env.company).ids if rec.product_id else False

    @api.depends('capsule_id', 'hours', 'net_price', 'date_from', 'tax_id')
    def _compute_amounts(self):
        """Compute the price based on the capsule's product price and the number of hours."""
        for line in self:
            if line.capsule_id and line.hours and line.tax_id:
                net_price = line.net_price
                amount_tax_vals = line.tax_id[0].compute_all(price_unit=net_price, currency=False, quantity=line.hours,
                                                             product=line.capsule_id.product_id,
                                                             partner=line.voucher_id.partner_id)
                total_excluded = amount_tax_vals.get('total_excluded')
                total_included = amount_tax_vals.get('total_included')
                amount_tax = total_included - total_excluded

            else:
                total_excluded = 0.0
                amount_tax = 0.0
                total_included = 0.0
            line.write({'total_excluded': total_excluded, 'amount_tax': amount_tax, 'total_included': total_included, })

    @api.constrains('date_from', 'hours')
    def _check_date_from_and_hours(self):
        """Ensure that:
           - date_from is in the future
           - hours is a positive integer (not float/decimal)"""
        for line in self:
            if line.date_from and fields.Datetime.from_string(line.date_from) < fields.Datetime.now():
                raise UserError("The start date must be in the future.")
            if line.hours <= 0:
                raise UserError("Hours must be a positive integer.")
            if not isinstance(line.hours, int):
                raise UserError("Hours must be a whole number (integer).")

    @api.depends('date_from', 'hours')
    def _compute_date_to(self):
        """Compute the end date based on start date and hours."""
        for line in self:
            if line.date_from and line.hours:
                line.date_to = fields.Datetime.to_string(
                    fields.Datetime.from_string(line.date_from) + timedelta(hours=line.hours))
            else:
                line.date_to = False

    def action_create_reservation(self, partner_id=None, expire_on=None):
        """Create a reservation from the voucher line.
        This method is called when the user wants to create a reservation from the voucher line."""
        self.ensure_one()
        if not self.capsule_id:
            raise UserError(_("A capsule must be selected to create a reservation."))
        reservation_vals = {
            'capsule_id': self.capsule_id.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'hours': self.hours,
            'customer': partner_id.name or self.voucher_id.partner_id.name,
            'partner_id': partner_id.id or self.voucher_id.partner_id.id,
            'product_id': self.product_id.id,
            'phone': partner_id.phone or self.voucher_id.partner_id.phone,
            'email': partner_id.email or self.voucher_id.partner_id.email,
            'branch_id': self.capsule_id.branch_id.id,
            'expire_on': expire_on,
        }
        reservation = self.env['reservation'].create(reservation_vals)
        self.reservation_id = reservation.id
        return reservation
