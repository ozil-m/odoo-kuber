# -*- coding: utf-8 -*-
import logging
from odoo import http, fields
from odoo.http import request
from odoo.tools import config
from datetime import datetime
import re

_logger = logging.getLogger(__name__)


def get_states_info(record):
    """
    Returns a dictionary with state information including ID, name in English and Arabic,
    """
    return {
        'id': record.id,
        'code': record.code,
        'name_en': record.name,
        'name_ar': record.with_context(lang='ar_001').name,
        'country_id': record.country_id.id,
        'country_name_en': record.country_id.name,
        'country_name_ar': record.country_id.with_context(lang='ar_001').name,
    }


def get_customer_info(customer):
    """ Helper function to extract customer information in a structured format.
    """
    return {
        'id': customer.id,
        'ref': customer.ref or None,
        'membershipId': customer.membership_id or None,
        'name': customer.name or None,
        'phone': customer.phone or None,
        'email': customer.email or None,
        'passport': customer.passport or None,
        'gender': customer.gender or None,
        'birth_date': customer.birth_date or None,
        'country_id': {
            'id': customer.country_id.id,
            'name_en': customer.country_id.name,
            'name_ar': customer.country_id.with_context(lang='ar_001').name} if customer.country_id else None,
        'state_id': {
            'id': customer.state_id.id,
            'name_en': customer.state_id.name,
            'name_ar': customer.state_id.with_context(lang='ar_001').name} if customer.state_id else None,
        'address': customer.street or None,
        'title_id': {
            'id': customer.title.id,
            'name_en': customer.title.name,
            'name_ar': customer.title.with_context(lang='ar_001').name,
            'shortcut_en': customer.title.shortcut,
            'shortcut_ar': customer.title.with_context(lang='ar_001').shortcut,
        } if customer.title else None,
    }


class KcHayyakPartner(http.Controller):


    @http.route(['/portal/states/get'], type="json", auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def get_states(self, country_id=None):
        """
        Fetches states based on the event or country code.
        """
        try:
            domain = []
            if country_id:
                domain = [('country_id', '=', int(country_id))]
            records = request.env['res.country.state'].sudo().search(domain)
            if not records:
                return {'code': 500, 'data': []}

            result = [get_states_info(record) for record in records]
            return {'code': 200, 'data': result}
        except Exception as e:
            _logger.error(
                f"\n*******************get_states************** An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/portal/title/get'], type="json", auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def get_titles(self):
        """
        Retrieve all title records.
        """
        try:
            results = request.env['res.partner.title'].sudo().search([])
            vals = [{
                'id': result.id,
                'name_en': result.name,
                'name_ar': result.with_context(lang='ar_001').name,
                'shortcut_en': result.shortcut,
                'shortcut_ar': result.with_context(lang='ar_001').shortcut,
            } for result in results]

            return {'code': 200, 'data': vals}
        except Exception as e:
            _logger.error(
                f"\n********************get_titles************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/portal/countries/get'], type="json", auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def get_countries(self):
        """
        Fetches all countries from the res.country model and returns them in a structured format.
        """
        try:
            domain = []
            results = request.env['res.country'].sudo().search(domain)
            vals = [{
                'id': result.id,
                'code': result.code,
                'phone_code': result.phone_code,
                'name_en': result.name,
                'name_ar': result.with_context(lang='ar_001').name,
            } for result in results]

            return {'code': 200, 'data': vals}
        except Exception as e:
            _logger.error(
                f"\n*******************get_countries************** An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/portal/subscribers/get'], type="json", auth='bearer', methods=["GET"], csrf=False, cors='*')
    def get_customer(self, **kw):
        """ Fetches customer data based on subscriber_id or returns all customers for Hayyak app.
        """
        try:
            subscriber_id = kw.get('subscriberId', False)
            membership_id = kw.get('membershipId', False)
            phone = kw.get('phone', False)
            email = kw.get('email', False)
            domain = [('hayyak_app', '=', True)]

            if subscriber_id:
                domain.append(('subscriberId', '=', subscriber_id))

            elif membership_id:
                domain.append(('membership_id', '=', membership_id))

            elif phone:
                domain.append(('phone', '=', phone))

            elif email:
                domain.append(('email', '=', email))
            else:
                return {'code': 400, 'error': 'Missing subscriberId, phone, or email', 'data': []}
            customers = request.env['res.partner'].sudo().search(domain)
            result = [get_customer_info(customer) for customer in customers]
            return {'code': 200, 'data': result}

        except Exception as e:
            # Log the error and return a user-friendly message
            _logger.error(f"An error occurred: {str(e)}")
            return {'code': 500, 'error': 'Something went wrong', 'data': []}


    @http.route(['/portal/subscriber/create'], type="json", auth='bearer', methods=["POST"], csrf=False, cors='*')
    def create_subscriber(self, **kw):
        """ Creates a new guest (child) for an existing customer (subscriber).
        """
        required_fields = ['name', 'phone', 'gender', 'subscriberId',"membershipId"]
        missing_fields = [field for field in required_fields if not kw.get(field)]
        if missing_fields:
            return {'code': 400, 'error': f"Missing required fields: {', '.join(missing_fields)}", 'data': []}

        try:
            check_subscriber_id = http.request.env['res.partner'].search([('ref', '=', kw.get('subscriberId'))])
            if check_subscriber_id:
                return {'code': 404, 'data': 'subscriberId already exists.'}
            country_id = kw.get('country_id', False)
            if country_id:
                country_exists = request.env['res.country'].sudo().search([('id', '=', country_id)], limit=1)
                if not country_exists:
                    return {'code': 400, 'error': 'Invalid country_id', 'data': []}

            state_id = kw.get('state_id', False)
            state_exists = False
            if state_id:
                state_exists = request.env['res.country.state'].sudo().search([('id', '=', state_id)], limit=1)
                if not state_exists:
                    return {'code': 400, 'error': 'Invalid state_id', 'data': []}

            gender = kw.get('gender', False)
            if gender and gender not in ['male', 'female']:
                return {'code': 400, 'error': 'Invalid male', 'data': []}
            vals = {
                'ref': kw.get('subscriberId', False),
                'name': kw.get('name', False),
                'phone': kw.get('phone', False),
                'email': kw.get('email', False),
                'title': kw.get('title_id', False),
                'passport': kw.get('passport', False),
                'birth_date': kw.get('birth_date', False),
                'gender': kw.get('gender', False),
                'country_id': state_exists.country_id.id if state_id else False,
                'state_id': state_id,
                'street': kw.get('address', False),
                'hayyak_app': True,
                'company_id': request.env.user.company_id.id if request.env.user.company_id else False,
            }
            customer = request.env['res.partner'].sudo().create(vals)
            return {'code': 201, 'message': 'Created successfully', 'data': customer.id}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/portal/subscriber/update'], type="json", auth='bearer', methods=["POST"], csrf=False, cors='*')
    def update_subscriber(self, **kw):
        """ Updates an existing subscriber (res.partner) based on subscriber_id. """
        subscriber_id = kw.get('subscriber_id')
        if not subscriber_id:
            return {'code': 400, 'error': 'Missing subscriber_id', 'data': []}

        try:
            subscriber = request.env['res.partner'].sudo().browse(int(subscriber_id))
            if not subscriber.exists():
                return {'code': 404, 'error': 'Subscriber not found', 'data': []}

            # Validate country_id if provided
            country_id = kw.get('country_id', False)
            if country_id:
                country_exists = request.env['res.country'].sudo().search([('id', '=', country_id)], limit=1)
                if not country_exists:
                    return {'code': 400, 'error': 'Invalid country_id', 'data': []}

            # Validate state_id if provided
            state_id = kw.get('state_id', False)
            if state_id:
                state_exists = request.env['res.country.state'].sudo().search([('id', '=', state_id)], limit=1)
                if not state_exists:
                    return {'code': 400, 'error': 'Invalid state_id', 'data': []}

            # Validate gender
            gender = kw.get('gender', False)
            if gender and gender not in ['male', 'female']:
                return {'code': 400, 'error': 'Invalid gender', 'data': []}

            vals = {}
            allowed_fields = {
                'ref': 'ref',
                'name': 'name',
                'phone': 'phone',
                'email': 'email',
                'title_id': 'title',
                'passport': 'passport',
                'birth_date': 'birth_date',
                'gender': 'gender',
                'country_id': 'country_id',
                'state_id': 'state_id',
                'address': 'street',
            }

            for input_key, field_name in allowed_fields.items():
                if kw.get(input_key) is not None:
                    vals[field_name] = kw.get(input_key)

            if vals:
                subscriber.write(vals)

            return {'code': 200, 'message': 'Updated successfully', 'data': get_customer_info(subscriber)}
        except Exception as e:
            _logger.error(f"\n********** Error updating subscriber: {str(e)}")
            return {'code': 500, 'error': 'Something went wrong', 'data': []}
