# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from datetime import timedelta, datetime
from .booking import convert_date_to_utc
_logger = logging.getLogger(__name__)




class PaidServices(http.Controller):


    @http.route(['/hayyak_app/lounge/paid_services/delete'], type="json", auth='bearer', methods=["POST"], )
    def release_reservation(self, **kw):
        """ Releases an existing reservation.
        """
        try:
            reservation_id = kw.get('holdID', False)
            if not reservation_id:
                return {'code': 400, 'error': 'Missing required holdID', 'data': []}
            reservation = request.env['voucher.line'].sudo().browse(reservation_id)
            if not reservation.exists():
                return {'code': 400, 'error': 'hold not found', 'data': []}
            reservation.unlink()
            return {'code': 200, 'message': 'Deleted successfully', 'data': []}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/hayyak_app/lounge/paid_services/extend'], type="json", auth='bearer', methods=["POST"], )
    def extend_reservation(self, **kw):
        """ extend an existing reservation.
        """
        try:
            reservation_id = kw.get('holdID', False)
            if not reservation_id:
                return {'code': 400, 'error': 'Missing required holdID', 'data': []}
            reservation = request.env['voucher.line'].sudo().browse(reservation_id)
            if not reservation.exists():
                return {'code': 400, 'error': 'hold not found', 'data': []}
            expire_after_str = request.env['ir.config_parameter'].sudo().get_param('expire_after', default='0')
            expire_after = float(expire_after_str)  # convert to float
            now_utc = datetime.utcnow()
            expire_on = now_utc + timedelta(minutes=expire_after)  # adjust unit if needed
            if expire_after > 0:
                reservation.reservation_id.expire_on = expire_on
            return {'code': 200, 'message': 'Extended successfully',
                    'data': {"holdID": reservation.id, "expire_on": expire_on}}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/hayyak_app/lounge/paid_services/create'], type="json", auth='bearer', methods=["POST"], )
    def create_reservation(self, **kw):
        """
        Creates a new reservation for a subscriber in a specific capsule.
        """
        try:
            required_fields = ['subscriberId', 'capsuleId', 'slotStartUtc', 'slotEndUtc', 'grossPrice',
                               'netPrice']
            missing_fields = [field for field in required_fields if not kw.get(field)]

            if missing_fields:
                return {
                    'code': 404,
                    'data': [],
                    'message': f"Missing required fields: {', '.join(missing_fields)}"
                }

            customer = request.env['res.partner'].sudo().search([('ref', '=', kw.get('subscriberId'))], limit=1)
            if not customer:
                return {'code': 400, 'error': 'subscriber not found', 'data': []}

            room_id = int(kw.get('capsuleId'))
            room = request.env['room'].sudo().browse(room_id)
            if not room.exists():
                return {'code': 400, 'error': f'capsule ID ({room_id}) not found.', 'data': []}

            date_from_utc = convert_date_to_utc(kw.get('slotStartUtc').replace('T', ' '))
            date_to_utc = convert_date_to_utc(kw.get('slotEndUtc').replace('T', ' '))
            # Check 1: date_from_utc cannot be in the past
            now_utc = datetime.utcnow()
            if date_from_utc < now_utc:
                return {'code': 400, 'error': "Slot start time cannot be in the past.", 'data': []}

            # Check 2: date_to_utc cannot be before date_from_utc
            if date_to_utc <= date_from_utc:
                return {'code': 400, 'error': "Slot end time must be after slot start time.", 'data': []}
            is_room_available = room.is_room_available(
                date_from=date_from_utc,
                date_to=date_to_utc,
            )
            if not is_room_available:
                return {'code': 400,
                        'error': f'({room.service_id.name} - {room.name}) is not available at this time',
                        'data': []}
            reservation_obj = request.env['voucher.line'].sudo()
            reservation = reservation_obj.create({
                'product_id': room.product_id.id,
                'room_id': room.id,
                'price_unit': kw.get('grossPrice'),
                'discount_amount': kw.get('discountAmount'),
                'net_price': kw.get('netPrice'),
                'hours': 1,
                'date_from': date_from_utc,
                'date_to': date_to_utc,
            })
            # Fetch expire_after from system params (returns string)
            expire_after_str = request.env['ir.config_parameter'].sudo().get_param('expire_after', default='0')
            expire_after = float(expire_after_str)  # convert to float
            expire_on = None
            if expire_after > 0:
                expire_on = now_utc + timedelta(minutes=expire_after)  # adjust unit if needed
            reservation.action_create_reservation(customer, expire_on)

            return {'code': 201, 'message': "Created successfully",
                    'data': {"holdID": reservation.id, "expire_on": expire_on}}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message