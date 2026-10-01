# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from .api_tools import translate_selection, convert_datetime_to_timezone
from odoo.tools import config
from datetime import datetime, date
import pytz
from dateutil import parser

_logger = logging.getLogger(__name__)


def get_base_url():
    """ Return the base URL of the Odoo instance."""
    return request.env['ir.config_parameter'].get_param('web.base.url')



def get_order_line_info(line):
    """ Extracts relevant information from a sale order line.
    """
    return {
        "serviceId": line.room_id.service_id.id or None,
        "capsuleId": line.room_id.id or None,
        "slotStartUtc": convert_datetime_to_timezone(line.date_from) or None,
        "slotEndUtc": convert_datetime_to_timezone(line.date_to) or None,
        # "hours": line.hours,
        "name_en": line.room_id.name or None,
        "name_ar": line.room_id.with_context(lang='ar_001').name or None,
        # "note": line.note or None,
        "grossPrice": round(line.price_unit, 2),
        "discountAmount": round(line.discount_amount, 2),
        "netPrice": round(line.net_price, 2),
        "total_excluded": round(line.total_excluded, 2),
        "amount_tax": round(line.amount_tax, 2),
        "total_included": round(line.total_included, 2),
        "tax_id": line.tax_id[0].read(fields=['name', 'amount']) if line.tax_id else [],
    }


def get_attachment(order):
    """ Returns the attachment URL for a given order.
    """
    result = []
    attachment = http.request.env['ir.attachment']
    attachment_ids = attachment.search(
        [('res_model', '=', "lounge.voucher"), ('res_id', '=', order.id)])
    for attach in attachment_ids:
        url = f"{get_base_url()}/web/content/{attach.id}"
        result.append(
            {
                'name': attach.name,
                'url': url,
            }
        )
    return result


def get_booking_info(order):
    """ Extracts relevant information from a sale order.
    """
    return {
        "id": order.id,
        "segmentId": order.segment_id or None,
        "cityCode": order.branch_id.airport_id.iata_code or None,
        "arrivalDate": convert_datetime_to_timezone(order.departure_date) or None,
        'loungeId': order.branch_id.id or None,
        'amenities': [get_order_line_info(line) for line in order.line_ids] if order.line_ids else [],
        # "note": order.note or None,
        "guestsCount": order.quantity,
        "guestsGrossFee": order.price,
        "guestsDiscountAmount": order.discount_amount,
        "guestsNetFee": order.net_price,
        "total_excluded": order.total_excluded,
        "tax_id": order.tax_id[0].read(fields=['name', 'amount']) if order.tax_id else [],
        "amount_tax": round(order.amount_tax, 2),
        "total_included": round(order.total_included),
        "status": translate_selection(order, 'state') if order.state else None,
        "status_code": order.state or None,
        'used_on': convert_datetime_to_timezone(order.used_on) or None,
        'qr_code': f"{get_base_url()}/web/image/lounge.voucher/{order.id}/qr_code" if order.qr_code else None,
        'attachments': get_attachment(order),
    }


def to_aware_utc(dt):
    """ Converts a naive datetime to an aware datetime in UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=pytz.UTC)
    return dt.astimezone(pytz.UTC)


def convert_date_to_utc(date_time_str):
    """
    Converts an ISO8601 date-time string to naive UTC datetime.
    """
    dt = parser.isoparse(date_time_str)

    # If no timezone info, assume Asia/Riyadh
    if dt.tzinfo is None:
        saudi_tz = pytz.timezone('Asia/Riyadh')
        dt = saudi_tz.localize(dt)

    # Convert to UTC and drop tzinfo for Odoo
    return dt.astimezone(pytz.UTC).replace(tzinfo=None)


def check_profile(partner):
    """Check if the partner profile is complete for booking."""
    required_fields = ['name', 'phone', 'gender', 'passport', 'email', 'subscriberId']
    missing_fields = [field for field in required_fields if not getattr(partner, field, False)]

    if missing_fields:
        return "Please complete your profile before booking: %s" % ', '.join(missing_fields)
    return False


class KcHayyakOrder(http.Controller):


    @http.route(['/hayyak_app/check_capsule_availability'], type="json", auth='bearer', methods=["GET"], csrf=False, cors='*')
    def check_room_availability(self, capsule_id, date_from=None):
        """ Fetches all lounges associated with a specific lounge ID.
        """
        try:
            room = request.env['room'].sudo().browse(capsule_id)
            if not room.exists():
                return {'code': 400, 'message': 'Capsule not found.', 'data': []}
            date_from_dt = None
            if date_from:
                try:
                    date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
                    if date_from_dt.date() < date.today():
                        return {'code': 400, 'error': 'Date cannot be in the past.', 'data': []}

                except ValueError:
                    return {'code': 400, 'error': 'Invalid date format. Expected YYYY-MM-DD.', 'data': []}

            slots = room.get_available_slots(date_from_dt)
            return {'code': 200, 'data': slots}
        except Exception as e:
            _logger.error(
                f"\n****************check_room_availability***************** An error occurred: {str(e)}")
            return {'code': 500, 'error': 'Something went wrong', 'data': []}


    @http.route(['/hayyak_app/bookings/get'], type="json", auth='bearer', methods=["GET"], csrf=False, cors='*')
    def get_hayyak_app_bookings_data(self, **kw):
        """ Fetches bookings for a specific customer or a specific booking by ID.
        """
        customer_id = kw.get('subscriberId', False)
        sky_central_ref = kw.get('bookingId', False)
        if not customer_id and not sky_central_ref:
            return {'code': 400, 'error': 'Missing required data', 'data': []}
        try:

            if customer_id:
                customer = request.env['res.partner'].sudo().search([('ref', '=', customer_id)], limit=1)
                if not customer:
                    return {'code': 400, 'error': 'Customer not found', 'data': []}
                domain = [('partner_id', '=', customer.id), ]
            else:
                domain = [('sky_central_ref', '=', sky_central_ref), ]
            bookings = request.env['lounge.voucher'].sudo().search(domain + [("hayyak_app", '=', True)])
            bookings_map = {}
            for booking in bookings:
                sky_central_ref = booking.sky_central_ref
                if sky_central_ref not in bookings_map:
                    bookings_map[sky_central_ref] = {
                        "bookingId": sky_central_ref,
                        "subscriberId": customer_id,
                        "segments": []
                    }

                bookings_map[sky_central_ref]["segments"].append(get_booking_info(booking))
            bookings = list(bookings_map.values())
            result = {
                'bookings':
                    bookings
            }
            return {'code': 200, 'data': result, }
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/hayyak_app/booking/create'], type="json", auth='bearer', methods=["POST"], )
    def create_booking(self, **kw):
        """ Creates a new booking for a subscriber in a specific lounge.
        """
        try:
            now_utc = datetime.utcnow()
            sky_central_ref = kw.get('bookingId')
            segments = kw.get('segments')
            customer_id = kw.get('subscriberId')
            result = []
            segment_required_fields = ['segmentId', 'loungeId', 'arrivalDate', 'guestsCount',
                                       'guestsGrossFee', 'guestsNetFee']
            customer = request.env['res.partner'].sudo().search([('ref', '=', customer_id)], limit=1)
            if not customer:
                return {'code': 400, 'error': 'subscriber not found', 'data': []}
            # profile_error = check_profile(customer)
            # if profile_error:
            #     return {'code': 400, 'data': [], "message": profile_error}
            _logger.info("\n\nsegments++++++++++++segments+++++++++++++++\n\n %s", segments)
            # Validate each segment
            for segment in segments:
                missing_fields = [field for field in segment_required_fields if not segment.get(field)]
                if missing_fields:
                    return {
                        'code': 404,
                        'data': [],
                        'message': f"Missing required fields in segment {segment.get}: {', '.join(missing_fields)}"
                    }

            for segment in segments:
                lounge_id = segment.get('loungeId')
                departure_date = segment.get('arrivalDate').replace('T', ' ')
                membership_tier_id = segment.get('membership_tier_id', False)
                quantity = segment.get('guestsCount')
                price = segment.get('guestsGrossFee')
                discount_amount = segment.get('guestsDiscountAmount', 0)
                net_price = segment.get('guestsNetFee')

                _logger.info("amenities type: %s, value: %s", type(segment.get("amenities")), segment.get("amenities"))

                _logger.info("amenities %s", segment.get('amenities', False))
                amenities = segment.get('amenities', [])

                branch_obj = request.env['res.branch'].sudo().browse(lounge_id)
                if not branch_obj:
                    return {'code': 400, 'error': 'Lounge not found', 'data': []}

                departure_date_naive = convert_date_to_utc(departure_date)
                vals = {
                    'partner_id': customer.id,
                    'departure_date': departure_date_naive,
                    'product_id': int(request.env['ir.config_parameter'].sudo().get_param("voucher_product_id")),
                    'title_id': customer.title.id if customer.title else False,
                    'email': customer.email,
                    'quantity': quantity,
                    'price': price,
                    'discount_amount': discount_amount,
                    'net_price': net_price,
                    'membership_tier_id': membership_tier_id,
                    'sky_central_ref': sky_central_ref,
                    'hayyak_app': True,
                    'partner': customer.name,
                    'mobile': customer.phone,
                    'branch_id': branch_obj.id,
                    'segment_id': segment.get('segmentId'),
                    'sc_json': str(kw),
                    'source': "Hayyak App",
                }
                booking = request.env['lounge.voucher'].create(vals)
                _logger.info("amenities %s", amenities)
                for amenity in amenities:
                    line = request.env['voucher.line'].sudo().browse(amenity)
                    _logger.info("line %s", line)
                    _logger.info("booking.id %s", booking.id)
                    if not line.exists():
                        return {'code': 400, 'error': f'reservation ID ({amenity}) not found.', 'data': []}
                    room = line.room_id
                    if line.voucher_id:
                        return {'code': 400,
                                'error': f'Reservation ({room.service_id.name} - {room.name}) is already linked to another booking.',
                                'data': []}
                    if line.reservation_id.expire_on and line.reservation_id.expire_on < now_utc:
                        return {'code': 400,
                                'error': f'Reservation for ({room.service_id.name} - {room.name}) has expired and cannot be used.',
                                'data': []}
                    line.sudo().write({'voucher_id': booking.id})  # Unlink from any existing voucher
                    if line.reservation_id:
                        line.reservation_id.expire_on = False
                booking.get_lines_tax_id()
                # booking.action_create_reservations()
                result.append({
                    "segmentId": segment.get('segmentId'),
                    "LmsBookingId": booking.id
                })
            return {'code': 201, 'message': "Created successfully",
                    'data': result}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/hayyak_app/booking/cancel'], type="json", auth='bearer', methods=["POST"])
    def cancel_booking(self, bookingId):
        """Cancels existing bookings if they are in draft state."""
        try:
            domain = [('sky_central_ref', '=', bookingId), ('hayyak_app', '=', True)]
            bookings = request.env['lounge.voucher'].sudo().search(domain)

            if not bookings:
                return {'code': 400, 'error': 'Booking not found', 'data': []}

            # Filter only bookings in draft state
            cancelable_bookings = bookings.filtered(lambda b: b.state == 'draft')
            if not cancelable_bookings:
                return {'code': 400, 'error': 'Booking(s) cannot be canceled', 'data': []}

            cancelable_bookings.action_cancel()
            result = {
                'bookingId': bookingId,
                'segments': [{
                    "segmentId": booking.segment_id,
                    "LmsBookingId": booking.id
                } for booking in cancelable_bookings],
            }

            return {
                'code': 200,
                'message': 'bookings canceled successfully',
                'data': result
            }
        except Exception as e:
            _logger.error(f"\n********************************* An error occurred: {str(e)}")
            return {'code': 500, 'error': 'Something went wrong', 'data': []}


    @http.route(['/hayyak_app/booking/payment'], type="json", auth='bearer', methods=["POST"], )
    def payment_order(self, bookingId, **kw):
        """ Creates a payment for a confirmed booking and reconciles it with the invoice.
        """
        try:
            moyasar_payment_ref = kw.get('sourceId', False)
            domain = [('sky_central_ref', '=', bookingId), ('hayyak_app', '=', True)]
            bookings = request.env['lounge.voucher'].sudo().search(domain)
            if not bookings:
                return {'code': 400, 'error': 'booking not found', 'data': []}
            bookings_to_process = bookings.filtered(lambda b: b.state == 'draft')
            if not bookings_to_process:
                return {'code': 400, 'error': 'booking(s) cannot be paid', 'data': []}
            for booking in bookings_to_process:
                booking.write({'moyasar_payment_ref': moyasar_payment_ref})

            # bookings_to_process.action_confirm()
            bookings_to_process.action_confirm()

            # request.env['lounge.voucher'].sudo().action_create_bulk_invoice(bookings_to_process)
            result = {
                'bookingId': bookingId,
                'segments': [{
                    "segmentId": booking.segment_id,
                    "LmsBookingId": booking.id
                } for booking in bookings],
            }
            return {'code': 200, 'message': 'Successful', 'data': result}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message
