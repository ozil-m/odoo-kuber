# -*- coding: utf-8 -*-
import logging
from odoo import http, fields
from odoo.http import request
from odoo.tools import config
from datetime import datetime, date

_logger = logging.getLogger(__name__)

_session_data = ['/hayyak/session']


def get_facilities(lounge):
    """ Fetches all facilities associated with a lounge and returns their details.
    """
    result = []
    for rec in lounge.facilities_ids:
        result.append({
            # 'id': rec.id,
            'name_en': rec.name,
            'name_ar': rec.with_context(lang='ar_001').name,
            'icon': rec.icon.cdn_url if rec.icon and rec.icon.cdn_url else "",
            'code': rec.code or None,
            # 'description_en': rec.description or None,
            # 'description_ar': rec.with_context(lang='ar_001').description or None,
        })
    return result


def get_slots(lounge):
    """ Fetches all slots associated with a lounge and returns their details.
    """
    rooms = request.env['room'].sudo().search([('branch_id', '=', lounge.id)], limit=1)
    service_map = {}
    for room in rooms:
        sid = room.service_id.id
        if sid not in service_map:
            service_map[sid] = {
                "service_id": sid,
                "service_name_en": room.service_id.name,
                "service_name_ar": room.service_id.with_context(lang='ar_001').name,
                "description_en": room.service_id.description or None,
                "description_ar": room.service_id.with_context(lang='ar_001').description or None,
                "price": room.service_id.price,
                'icon': room.service_id.icon.cdn_url if room.service_id.icon and room.service_id.icon.cdn_url else "",
                "capsules": []
            }
        service_map[sid]["capsules"].append({
            "id": room.id,
            "name_en": room.name,
            "name_ar": room.with_context(lang='ar_001').name,
            "timeSlots": room.get_available_slots(),
        })

    result = list(service_map.values())
    return result


def get_services(lounge):
    """ Fetches all services associated with a lounge and returns their details.
    """
    result = []
    for rec in lounge.services_ids:
        result.append({
            # 'id': rec.id,
            'name_en': rec.name,
            'name_ar': rec.with_context(lang='ar_001').name,
            'icon': rec.icon.cdn_url if rec.icon and rec.icon.cdn_url else "",
            'code': rec.code,
            # 'description_en': rec.description or None,
            # 'description_ar': rec.with_context(lang='ar_001').description or None,
        })
    return result


def get_images(lounge):
    """ Fetches all images associated with a lounge and returns their URLs.
    """
    result = []
    for attach in lounge.image_ids:
        if attach.cdn_url:
            result.append(attach.cdn_url)
    return result


# Helper Functions
def handle_exception(e, message="An error occurred"):
    """ Handles exceptions by logging the error and returning a structured response.
    """
    _logger.error(f"{message}: {str(e)}")
    return {'code': 500, 'message': str(e), 'data': []}


def required_params(*params):
    """ Decorator to check if required parameters are present in the request.
    """

    def decorator(func):
        """ Decorator function that checks for required parameters in the request.
        """

        def wrapper(*args, **kwargs):
            """ Wrapper function that checks for required parameters.
            """
            for param in params:
                if param not in kwargs or not kwargs[param]:
                    return {'code': 404, 'error': f'Missing required parameter: {param}', 'data': []}
            return func(*args, **kwargs)

        return wrapper

    return decorator


class KcHayyak(http.Controller):


    @http.route(_session_data, type="json", auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def get_session_data(self):
        """
        Returns the session ID for the current user.
        """
        data = {"session_id": request.session.sid}
        return {'code': 202, 'data': data, }


    @http.route(['/hayyak_app/countries'], type="json", auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def get_countries_data(self):
        """
        Fetches all countries that have lounges associated with branches.
        """
        try:
            def get_states_with_lounges(country):
                """ Fetches states associated with a given country that have lounges.
                """
                states_with_lounges = request.env['res.branch'].sudo().search(
                    [('state_id', 'in', country.state_ids.ids), ('hayyak_app', '=', True)]
                ).mapped('state_id')

                # Preparing the response
                return [{
                    'id': state.id,
                    'name_en': state.name,
                    'name_ar': state.with_context(lang='ar_001').name,
                    'code': state.code,
                    'country_en': state.country_id.name,
                    'country_ar': state.country_id.with_context(lang='ar_001').name,
                } for state in states_with_lounges]

            countries_with_lounges = request.env['res.branch'].sudo().search([('hayyak_app', '=', True)]).mapped(
                'state_id.country_id')

            # Preparing the response
            result = [{
                'id': country.id,
                'name_en': country.name,
                'name_ar': country.with_context(lang='ar_001').name,  # Arabic name
                'country_code': country.code,
                'states': get_states_with_lounges(country) if country.state_ids else [],
            } for country in countries_with_lounges]

            return {'code': 200, 'data': result}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/hayyak_app/airports'], type="json", auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def get_airports_data(self, **kw):
        """
        Fetches all airports with lounges, optionally filtered by country and state.
        """
        try:
            state_id = kw.get('state_id', False)
            country_id = kw.get('country_id', False)

            # Fetch country and state objects only if they are provided
            country = request.env['res.country'].sudo().browse(country_id) if country_id else None
            state = request.env['res.country.state'].sudo().browse(state_id) if state_id else None

            # Use search only once to get all required branches
            domain = [('hayyak_app', '=', True)]

            if country:
                if not country.exists():
                    return {'code': 404, 'message': 'Country not found.', 'data': []}
                domain.append(('state_id', 'in', country.state_ids.ids))

            if state:
                if not state.exists():
                    return {'code': 404, 'message': 'State not found.', 'data': []}
                domain.append(('state_id', '=', state.id))

            # Optimize search to retrieve airports with lounges directly
            branches = request.env['res.branch'].sudo().search(domain)
            airports = branches.mapped('airport_id')
            terminals = branches.mapped('terminal_id')
            result = []
            for airport in airports:
                terminal_data = []
                for terminal in terminals:
                    lounges = branches.filtered(
                        lambda l: l.airport_id.id == airport.id and l.terminal_id.id == terminal.id)
                    if lounges:
                        terminal_data.append({
                        'id': terminal.id,
                        'name_en': terminal.name,
                        'name_ar': terminal.with_context(lang='ar_001').name,
                        'lounges': [
                            {'id': lounge.id,
                             'images': get_images(lounge),
                             'name_en': lounge.name,
                             'name_ar': lounge.with_context(lang='ar_001').name,
                             'cost': lounge.access_price,
                             'description_en': lounge.description or None,
                             'description_ar': lounge.with_context(lang='ar_001').description or None,
                             'lounge_address_en': lounge.lounge_address or None,
                             'lounge_address_ar': lounge.with_context(lang='ar_001').lounge_address or None,
                             'timings_en': lounge.timings or None,
                             'timings_ar': lounge.with_context(lang='ar_001').timings or None,
                             'facilities': {
                                 'facilities_description_en': lounge.facilities_description or None,
                                 'facilities_description_ar': lounge.with_context(
                                     lang='ar_001').facilities_description or None,
                                 'facilities': get_facilities(lounge)} if get_facilities(lounge) else None,
                             'services': {
                                 'services_description_en': lounge.facilities_description or None,
                                 'services_description_ar': lounge.with_context(
                                     lang='ar_001').services_description or None,
                                 'services': get_services(lounge)} if get_services(lounge) else None,
                             # 'slots': get_slots(lounge),
                             } for lounge in lounges]
                    })

                result.append({
                    'id': airport.id,
                    'name_en': airport.name,
                    'name_ar': airport.with_context(lang='ar_001').name,
                    'iata_code': airport.iata_code or None,
                    'state': {
                        'id': airport.state_id.id,
                        'name_en': airport.state_id.name,
                        'name_ar': airport.state_id.with_context(lang='ar_001').name,  # Arabic name for state
                        'code': airport.state_id.code or None,
                        'country_id': airport.state_id.country_id.id,
                        'country_name_en': airport.state_id.country_id.name,
                        'country_name_ar': airport.state_id.country_id.with_context(lang='ar_001').name,

                    },
                    'terminals': terminal_data
                })

            return {'code': 200, 'data': result}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/hayyak_app/lounge'], type="json", auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def get_lounge_data(self, lounge_id):
        """ Fetches detailed information about a specific lounge by its ID.
        """
        try:
            if not lounge_id:
                return {'code': 404, 'error': 'Lounge ID is required', 'data': []}
            lounge = request.env['res.branch'].sudo().browse(lounge_id)
            if not lounge.exists():
                return {'code': 404, 'message': 'Lounge not found.', 'data': []}
            # airport = lounge.airport_id
            # terminal = lounge.terminal_id
            services = get_services(lounge)
            facilities = get_facilities(lounge)
            result = {
                # 'airport': {'id': airport.id,
                #             'name_en': airport.name,
                #             'name_ar': airport.with_context(lang='ar_001').name,
                #             'iata_code': airport.iata_code or None, },
                # 'state': {
                #     'id': airport.state_id.id,
                #     'name_en': airport.state_id.name,
                #     'name_ar': airport.state_id.with_context(lang='ar_001').name,  # Arabic name for state
                #     'code': airport.state_id.code or None,
                #     'country_id': airport.state_id.country_id.id,
                #     'country_name_en': airport.state_id.country_id.name,
                #     'country_name_ar': airport.state_id.country_id.with_context(lang='ar_001').name, },
                # 'terminal': {
                #     'id': terminal.id,
                #     'name_en': terminal.name,
                #     'name_ar': terminal.with_context(lang='ar_001').name},
                'id': lounge.id,
                'images': get_images(lounge),
                'name_en': lounge.name,
                'name_ar': lounge.with_context(lang='ar_001').name,
                'cost': lounge.access_price,
                'description_en': lounge.description or None,
                'description_ar': lounge.with_context(lang='ar_001').description or None,
                'lounge_address_en': lounge.lounge_address or None,
                'lounge_address_ar': lounge.with_context(lang='ar_001').lounge_address or None,
                'timings_en': lounge.timings or None,
                'timings_ar': lounge.with_context(lang='ar_001').timings or None,
                'facilities': {
                    'facilities_description_en': lounge.facilities_description or None,
                    'facilities_description_ar': lounge.with_context(
                        lang='ar_001').facilities_description or None,
                    'facilities': facilities} if facilities else None,
                'services': {
                    'services_description_en': lounge.facilities_description or None,
                    'services_description_ar': lounge.with_context(
                        lang='ar_001').services_description or None,
                    'services': services} if services else None,
                # 'slots': get_slots(lounge),
            }

            return {'code': 200, 'data': result}
        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")  # Logs the detailed error message
            return {'code': 500, 'error': 'Something went wrong', 'data': []}  # Return a user-friendly message


    @http.route(['/hayyak_app/lounge/paid_services'], type="json", auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def get_lounges_data(self, **kw):
        """
        Fetches all lounges associated with a specific lounge ID.
        If `capsules` is True, include capsule info in the response.
        """
        try:
            lounge_id = kw.get('lounge_id')
            date_from = kw.get('date_from', None)
            include_capsules = kw.get('include_capsules', False)  # expects 'true', True, or '1'

            if not lounge_id:
                return {'code': 404, 'error': 'Lounge ID is required', 'data': []}

            lounge = request.env['res.branch'].sudo().browse(lounge_id)
            if not lounge.exists():
                return {'code': 404, 'message': 'Lounge not found.', 'data': []}

            rooms = request.env['room'].sudo().search([('branch_id', '=', lounge_id)])
            _logger.info(f"**************************rooms found {rooms} ************************")
            if not rooms:
                return {'code': 200, 'data': []}

            date_from_dt = None
            if date_from:
                try:
                    date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
                    if date_from_dt.date() < date.today():
                        return {'code': 400, 'error': 'Date cannot be in the past.', 'data': []}
                except ValueError:
                    return {'code': 400, 'error': 'Invalid date format. Expected YYYY-MM-DD.', 'data': []}

            service_map = {}
            for room in rooms:
                sid = room.service_id.id
                if sid not in service_map:
                    service_map[sid] = {
                        "service_id": sid,
                        "service_name_en": room.service_id.name,
                        "service_name_ar": room.service_id.with_context(lang='ar_001').name,
                        "description_en": room.service_id.description or None,
                        "description_ar": room.service_id.with_context(lang='ar_001').description or None,
                        "price": room.service_id.price,
                        'icon': room.service_id.icon.cdn_url if room.service_id.icon and room.service_id.icon.cdn_url else "",
                    }
                    if include_capsules:
                        service_map[sid]["capsules"] = []  # only create key if requested

                if include_capsules:
                    service_map[sid]["capsules"].append({
                        "id": room.id,
                        "name_en": room.name,
                        "name_ar": room.with_context(lang='ar_001').name,
                        "timeSlots": room.get_available_slots(date_from_dt),
                    })

            result = list(service_map.values())

            return {'code': 200, 'data': result}

        except Exception as e:
            _logger.error(
                f"\n********************************* An error occurred: {str(e)}")
            return {'code': 500, 'error': 'Something went wrong', 'data': []}
