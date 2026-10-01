# -*- coding: utf-8 -*-
import logging

from odoo.exceptions import ValidationError, UserError

try:
    import base64
except ImportError:
    base64 = None
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class Sale(models.Model):
    """ This model represents sale."""
    _inherit = 'sale.order'

    def _get_config_param(self, param_name, error_msg=None):
        """Helper function to fetch system configuration parameters."""
        param = self.env['ir.config_parameter'].sudo().get_param(param_name)
        if not param and error_msg:
            raise UserError(error_msg)
        return param

    def notify_admin_for_failed_payments(self, message):
        """Helper function to notify managers via email and activity."""
        group = self.env.ref('base.group_system', raise_if_not_found=False)
        users = group.users
        for user in users:
            # Create an activity
            self.env['mail.activity'].create({
                'res_model_id': self.env['ir.model']._get('sale.order').id,
                'res_id': self.id,
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'summary': 'Payment Issue',
                'note': message,
                'date_deadline': fields.Date.today(),
                'user_id': user.id,
            })
            # template = self.env.ref('kc_hayyak.task_email_notify_admin_for_failed_payments').sudo()
            # template.send_mail(self.id, force_send=True)

    moyasar_payment_ref = fields.Char(string="Moyasar Payment Ref", required=False, )
    hayyak_app = fields.Boolean(string="", )

    def action_set_accounting_data(self):
        """ This method sets the accounting data for the sale order."""
        for rec in self:
            membership_account_department_id = int(self._get_config_param('membership_account_department_id',
                                                                     'Please configure the Analytic Account in the system parameters.'))
            membership_analytic_id = int(self._get_config_param('membership_analytic_id',
                                                           'Please configure the Analytic Account in the system parameters.'))
            rec.write({'department_id': membership_account_department_id, 'analytic_account_id': membership_analytic_id})

    def send_invoice_info(self):
        """ This method sends the invoice information to the caller via email.
        """
        for rec in self:
            invoice_id = rec.invoice_ids.filtered(lambda inv: inv.state in ['posted'])
            invoice = invoice_id and invoice_id[0] or False
            if invoice:
                subject = f"Invoice for Order Number {rec.name}فاتورة للطلب رقم "
                email_template = self.env.ref('kc_hayyak.einvoice_info_email_template')
                report_xml_id = 'einvoice.stander_invoice_id'
                report = rec.env.ref(report_xml_id)
                pdf_data = report._render_qweb_pdf(invoice.ids)
                data_record = base64.b64encode(pdf_data[0])
                attachment = rec.env['ir.attachment'].create({
                    'name': '%s.pdf' % rec.name,
                    'type': 'binary',
                    'datas': data_record,
                    'res_model': 'sale.order',
                    'res_id': rec.id,
                    'mimetype': 'application/pdf'
                })
                if rec.caller_id.email:
                    email_values = {
                        'subject': subject,
                        'email_from': rec.company_id.email_formatted or '',
                        'email_to': rec.caller_id.email,
                        'auto_delete': False,
                        'message_type': 'email',
                        'recipient_ids': [],
                        'partner_ids': [],
                        'scheduled_date': False,
                        'body_html': f"""
                                    <p>Dear {rec.partner_id.name},</p>
                                    <p> Your E-invoice has been issued.</p>
                                    <p>Best regards,</p>
                                    <p>Hayyak</p>
                                    <hr>
                                    <p dir="rtl">عزيزي {rec.caller_id.with_context(lang='ar_001').name},</p>
                                    <p dir="rtl">تم إصدار فاتةرتك الضريبية</p>
                                    <p dir="rtl">مع خالص التحيات،</p>
                                    <p dir="rtl">حياك</p>
                                """,
                        'attachment_ids': [(6, 0, [attachment.id])],
                    }
                    email_template.send_mail(rec.id, force_send=True,
                                             raise_exception=False,
                                             email_values=email_values)

    def action_create_payments(self, tier_name):
        """ Function to create a payment for the task.
        """
        for rec in self:
            try:
                membership_account_department_id = int(self._get_config_param('membership_account_department_id',
                                                                         'Please configure the Analytic Account in the system parameters.'))
                membership_analytic_id = int(self._get_config_param('membership_analytic_id',
                                                               'Please configure the Analytic Account in the system parameters.'))

                amount = rec.amount_total
                moyasar_journal_id = self._get_config_param('moyasar_journal_id',
                                                            'Please configure Moyasar Journal in the system parameters.')
                moyasar_journal = self.env['account.journal'].browse(int(moyasar_journal_id))
                if not moyasar_journal.exists():
                    moyasar_journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
                    _logger.info(
                        f"\n\n***************moyasar_journal not found , using {moyasar_journal.name} journal*************** id {moyasar_journal.id}")
                    return True

                partner_id = rec.partner_id.id
                label = f'Payment {rec.moyasar_payment_ref} for Sale Order #{rec.name} - {tier_name}'
                vals = {
                    "journal_id": moyasar_journal.id,
                    "payment_type": 'inbound',
                    "partner_type": 'customer',
                    "ref": label,
                    "amount": float(amount),
                    "partner_id": int(partner_id),
                    "company_id": rec.company_id.id or rec.env.company.id,

                }
                payment = self.env['account.payment'].sudo().with_context(company_id=rec.company_id.id).create(vals)
                for line in payment.move_id.line_ids:
                    line.sudo().write(
                        {'analytic_account_id': membership_analytic_id, 'department_id': membership_account_department_id, })
                payment.action_post()
                invoice = rec.invoice_ids[0]
                if invoice.state != 'posted':
                    invoice.action_post()
                if invoice.payment_state == 'paid':
                    return True
                else:
                    account_to_reconcile = invoice.line_ids.filtered(
                        lambda line: line.account_id.user_type_id.type in ('receivable', 'payable')).mapped(
                        'account_id')

                    # Get move lines from the invoice and payment
                    invoice_move_lines = invoice.line_ids.filtered(lambda line: line.account_id in account_to_reconcile)
                    payment_move_lines = payment.line_ids.filtered(lambda line: line.account_id in account_to_reconcile)

                    # Combine the move lines to reconcile
                    move_lines_to_reconcile = invoice_move_lines + payment_move_lines

                    # Reconcile the move lines
                    move_lines_to_reconcile.reconcile()
                    # rec.send_invoice_info()
                    return True
            except Exception as e:
                message = f'kc_hayyak Sales Payment Issue: \n' + str(e)
                _logger.info("kc_hayyak Error in processing Moyasar payment callback: %s", str(e))
                rec.sudo().notify_admin_for_failed_payments(message)
                return True
        return True

    @api.constrains('state')
    def _check_attachment(self):
        # form gr_delay module try to find a better way to fix
        for record in self:
            if record.state not in ['draft', 'cancel'] and not record.hayyak_app:
                attachments = self.env['ir.attachment'].search([
                    ('res_model', '=', self._name),
                    ('res_id', '=', record.id)
                ])
                # Check if there are fewer than 2 attachments
                if len(attachments) < 2:
                    raise ValidationError(_('You cannot send the quotation without attaching at least two documents.'))
