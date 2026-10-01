import logging
from datetime import timedelta
from odoo import http, _, fields
from odoo.http import request
from odoo.exceptions import AccessDenied
from odoo.addons.lms_management.models.business.utils_bcbp import parse_bcbp, convert_julian_to_date
from .tools import _json_body, translate_selection, _paged, attachment_read

_logger = logging.getLogger(__name__)


def _split_first_last(name_raw: str, name_clean: str):
    """LAST/FIRST[MIDDLE] → ('FIRST MIDDLE', 'LAST'), fallback to tokens."""
    s = (name_raw or "").strip()
    if "/" in s:
        left, right = s.split("/", 1)
        return (right or "").strip(), (left or "").strip()
    parts = (name_clean or "").split()
    if not parts:
        return "", ""
    return (" ".join(parts[1:]) if len(parts) > 1 else ""), parts[0]


def _find_airline_by_iata2(iata2: str):
    Airline = request.env["lms.airline"].sudo()
    c = (iata2 or "").strip().upper()[:2]
    if not c:
        return False
    return Airline.search([("iata_code", "=", c)], limit=1) or False


def _find_rule(airline, compartment_code: str):
    """Pick rule for airline + BCBP cabin letter (F/J/W/Y), ranked by 'rank'."""
    if not airline:
        return False
    Rule = request.env["booking.rule"].sudo()
    dom = [("airline_id", "=", airline.id)]
    if compartment_code:
        dom.append(("cabin_class", "=", (compartment_code or "").upper()))
    return Rule.search(dom, order="rank asc, id asc", limit=1) or False


def _make_passenger_vals_from_parsed(visit_id, data, rule, airline):
    first_name, last_name = _split_first_last(getattr(data, "passenger_name_raw", ""), data.passenger_name)
    product_name = False
    product_price = 0.0
    if rule and getattr(rule, "product_id", False):
        product_name = rule.product_id.display_name
        try:
            product_price = rule.product_id.lst_price
        except Exception:
            product_price = 0.0
    flight_date = convert_julian_to_date(data.flight_date_julian)
    return {
        "visit_id": visit_id,
        "type": "main",
        "boarding_pass_raw": getattr(data, "raw", None) or "",
        "passenger_title": (data.passenger_name or "").strip(),
        "first_name": first_name,
        "last_name": last_name,
        "pnr": data.pnr or "",
        "airline": (data.operating_carrier or "").upper(),
        "airline_id": airline.id if airline else False,
        "class_code": (data.compartment_code or "").upper(),
        "class_id": rule.id if rule else False,
        "seat_number": (data.seat_number or "").upper(),
        "flight_number": f"{(data.operating_carrier or '').strip()}{(data.flight_number or '').strip()}",
        "flight_sequence": data.check_in_sequence or "",
        "flight_from": (data.from_airport or "").upper(),
        "flight_to": (data.to_airport or "").upper(),
        "flight_date": flight_date,
        "ticket": data.ticket_number or "",
        "fqtv": data.fqtv or "",
        "product_name": product_name,
        "product_price": product_price,
    }


def _visit_dict(visit):
    access_time_window = int(request.env['ir.config_parameter'].sudo().get_param('lms.access_time_window') or 4)
    return {
        "id": visit.id,
        'uuid': visit.uuid or None,
        'create_by': {'id': visit.create_uid.id, 'name': visit.create_uid.name} if visit.create_uid else None,
        "create_date": visit.create_date and visit.create_date.isoformat() or None,
        "name": visit.name or None,
        "lounge": {'id': visit.lounge_id.id, 'name': visit.lounge_id.name} if visit.lounge_id else None,
        "branch_id": {'id': visit.branch_id.id, 'name': visit.branch_id.name} if visit.branch_id else None,
        "access_method": visit.access_method or None,
        "access_method_label": translate_selection(visit, 'access_method') or None,
        "voucher_id": {'id': visit.voucher_id.id, 'name': visit.voucher_id.name} if visit.voucher_id else None,
        "access_date": visit.access_date and visit.access_date.isoformat() or None,
        "access_time_window": access_time_window,
        "access_expire_on": (
                visit.access_date + timedelta(hours=access_time_window)).isoformat() if visit.access_date else None,
        "access_state": 'expired' if visit.access_date and (fields.Datetime.now() >
                                                            visit.access_date + timedelta(
                    hours=access_time_window)) else 'valid',
        "business_partner": {'id': visit.business_partner_id.id, 'name': visit.business_partner_id.name,
                             'type': visit.business_partner_id.partner_type} if visit.business_partner_id else None,
        "state": visit.state or None,
        "state_label": translate_selection(visit, 'state') or None,
        "invoicing_status": visit.invoicing_status or None,
        "invoicing_status_label": translate_selection(visit, 'invoicing_status') or None,
        "type": visit.type or None,
        "type_label": translate_selection(visit, 'type') or None,
        "passenger_title": visit.passenger_title or None,
        "first_name": visit.first_name or None,
        "last_name": visit.last_name or None,
        "airline_id": {'id': visit.airline_id.id, 'name': visit.airline_id.name,
                       'code': visit.airline_id.code} if visit.airline_id else None,
        "acceptance_rule": {'id': visit.acceptance_rule_id.id, 'name': visit.acceptance_rule_id.display_name,
                            'type': visit.acceptance_rule_id.type,
                            'type_label': translate_selection(visit.acceptance_rule_id, 'type'),
                            } if visit.acceptance_rule_id else None,
        "pnr": visit.pnr or None,
        "class_code": visit.class_code or None,
        "class_name": visit.class_name or None,
        "seat_number": visit.seat_number or None,
        "flight_number": visit.flight_number or None,
        "flight_sequence": visit.flight_sequence or None,
        "flight_from": visit.flight_from or None,
        "flight_to": visit.flight_to or None,
        "flight_date": visit.flight_date and visit.flight_date.isoformat() or None,
        "ticket": visit.ticket or None,
        "fqtv": visit.fqtv or None,
        "product_name": visit.product_id.name or None,
        "product_price": visit.product_price or None,
        "boarding_pass_raw": visit.boarding_pass_raw or None,
        # 'attachments': attachment_read(visit.id, visit._name) or None,
        "child_ids": [_visit_dict(child) for child in visit.child_ids],
    }


# -------------------------------------------------
# Business API (BCBP, visits)
# -------------------------------------------------
class LmsBusinessController(http.Controller):

    @http.route('/lms/api/bcbp/check', type='json', auth='bearer', methods=['POST', ], csrf=False, cors='*')
    def check_bcbp(self, **kw):
        """Parse a BCBP string and return ALL fields + enrichment (airline, rule, product)."""
        try:
            payload = _json_body(**kw)
            visit_model = request.env['lms.visit']
            access_date = fields.Datetime.now()
            bcbp_raw = payload.get("bcbp_raw") or payload.get("bcbp") or ""
            if not bcbp_raw:
                return {"code": 400, "message": "Missing 'bcbp_raw'."}
            # Duplication check:  same boarding_pass_raw
            # within 4 hours (before access_date)
            bcbp_check_period = int(request.env['ir.config_parameter'].sudo().get_param('lms.bcbp_check_period') or 24)
            four_hours_before = access_date - timedelta(hours=bcbp_check_period)

            visit = visit_model.search([
                ('boarding_pass_raw', '=', bcbp_raw),
                ('access_date', '>=', fields.Datetime.to_string(four_hours_before)),
                ('access_date', '<=', fields.Datetime.to_string(access_date)), ], limit=1)

            return {'code': 200, 'data': _visit_dict(visit) if visit else None,}
        except Exception as e:
            _logger.error("check_bcbp error: %s", e)
            return {'code': 500, 'message': str(e)}

    @http.route('/lms/api/visit/create', type='json', auth='bearer', methods=['POST', ], csrf=False,
                cors='*')
    def create_visits(self, **kw):
        """Create multiple visits (branch-based) and optional passenger lines.
           Each visit should contain required fields or a BCBP per passenger for auto-fill."""
        try:
            vals = _json_body(**kw)
            visits_data = vals.get('visits', [])
            if not isinstance(visits_data, list) or not visits_data:
                return {'code': 400, 'message': "Request must contain a non-empty list 'visits'.", 'data': []}

            visit_model = request.env['lms.visit'].sudo()
            results = []

            for visit_vals in visits_data:
                uuid = visit_vals.get('uuid')
                result_entry = {'uuid': uuid}

                try:
                    # Required fields
                    required_fields = [
                        'uuid', 'access_date', 'lounge_id', 'access_method', 'first_name',
                        'last_name', 'type', 'product_id', 'boarding_pass_raw']
                    missing_fields = [f for f in required_fields if not visit_vals.get(f)]
                    if missing_fields:
                        result_entry.update({
                            'status': 'error',
                            'message': f"Missing required fields: {', '.join(missing_fields)}"})
                        results.append(result_entry)
                        continue

                    lounge_id = visit_vals.get('lounge_id')
                    lounge = request.env['lms.lounge'].sudo().browse(lounge_id)
                    if not lounge.exists():
                        result_entry.update({
                            'status': 'error',
                            'message': f"Invalid lounge_id: {lounge_id}"
                        })
                        results.append(result_entry)
                        continue

                    pricelist_id = lounge.pricelist_id
                    if not pricelist_id or not pricelist_id.exists():
                        result_entry.update({
                            'status': 'error',
                            'message': f"Lounge {lounge.name} (id: {lounge_id}) has no pricelist assigned."
                        })
                        results.append(result_entry)
                        continue

                    product_id = visit_vals.get('product_id')
                    product = request.env['product.product'].sudo().browse(product_id)
                    if not product.exists():
                        result_entry.update({
                            'status': 'error',
                            'message': f"Invalid product_id: {product_id}"
                        })
                        results.append(result_entry)
                        continue
                    voucher_id = visit_vals.get('voucher_id', False)
                    if voucher_id:
                        voucher = request.env['lounge.voucher'].sudo().browse(voucher_id)
                        if not voucher or not voucher.exists():
                            result_entry.update({
                                'status': 'error',
                                'message': f"Invalid voucher_id: {voucher_id}"
                            })
                            results.append(result_entry)
                            continue

                    acceptance_rule_id = visit_vals.get('acceptance_rule_id')
                    acceptance_rule = request.env['acceptance.rule'].sudo().browse(acceptance_rule_id)
                    if not acceptance_rule.exists():
                        result_entry.update({
                            'status': 'error',
                            'message': f"Invalid acceptance_rule_id: {acceptance_rule_id}"
                        })
                        results.append(result_entry)
                        continue

                    # Validate payment method if provided
                    payment_method_id = visit_vals.get('payment_method_id', False)
                    if payment_method_id:
                        payment_method = request.env['lms.payment.method'].sudo().browse(payment_method_id)
                        if not payment_method.exists():
                            result_entry.update({
                                'status': 'error',
                                'message': f"Invalid payment_method_id: {payment_method_id}"
                            })
                            results.append(result_entry)
                            continue

                    uuid = visit_vals.get('uuid')
                    guest_type = visit_vals.get('type')
                    if guest_type not in ['main', 'guest']:
                        return {'code': 400, 'message': f"Invalid type: {guest_type}. Must be 'main' or 'guest'."}
                    parent_visit_id = False
                    if guest_type == 'guest':
                        parent_visit_id = visit_model.search([('uuid', '=', uuid), ('type', '=', 'main')], limit=1)
                        if not parent_visit_id or not parent_visit_id.exists():
                            result_entry.update({
                                'status': 'error',
                                'message': f"No main visit found with uuid: {uuid} for guest entry."
                            })
                            results.append(result_entry)
                            continue
                    airline_id = visit_vals.get('airline_id', False)
                    if airline_id:
                        airline = request.env['business.partner'].search(
                            [('id', '=', int(airline_id)), ('partner_type', '=', 'airline')], limit=1)
                        if not airline.exists():
                            result_entry.update({
                                'status': 'error',
                                'message': f"Invalid airline_id: {airline_id}"
                            })
                            results.append(result_entry)
                            continue

                    boarding_pass_raw = visit_vals.get('boarding_pass_raw')
                    access_method = visit_vals.get('access_method')
                    access_date_str = visit_vals.get('access_date')
                    access_date = fields.Datetime.from_string(access_date_str)

                    # Duplication check:  same boarding_pass_raw
                    # within 4 hours (before access_date)
                    four_hours_before = access_date - timedelta(hours=4)

                    duplicated_visit = visit_model.search([
                        ('boarding_pass_raw', '=', boarding_pass_raw),
                        ('access_method', '=', access_method),
                        ('access_date', '>=', fields.Datetime.to_string(four_hours_before)),
                        ('access_date', '<=', access_date_str), ], limit=1)

                    if duplicated_visit:
                        result_entry.update({'status': 'duplicated'})
                        results.append(result_entry)
                        continue

                    # Create visit
                    product_price = pricelist_id._get_product_price(product, 1.0, )
                    first_name = visit_vals.get('first_name')
                    last_name = visit_vals.get('last_name')
                    new_visit = visit_model.create({
                        'uuid': uuid,
                        'lounge_id': lounge_id,
                        'access_method': access_method,
                        'access_date': access_date_str,
                        # 'business_partner_id': business_partner_id,
                        'acceptance_rule_id': acceptance_rule_id,
                        'first_name': first_name,
                        'last_name': last_name,
                        'type': guest_type,
                        'product_id': product_id,
                        'product_price': product_price,
                        'parent_id': parent_visit_id.id if parent_visit_id else False,
                        'voucher_id': voucher_id,
                        'passenger_title': f"{first_name} {last_name}",
                        'airline_id': airline_id,
                        'boarding_pass_raw': boarding_pass_raw,
                        'payment_method_id': payment_method_id,
                        'access_doc_id': visit_vals.get('access_doc_id', False),
                        'booking_ref': visit_vals.get('booking_ref', False),
                        'state': visit_vals.get('state', 'confirmed'),
                        'pnr': visit_vals.get('pnr', False),
                        'airline_code': visit_vals.get('airline_code', False),
                        'class_code': visit_vals.get('class_code', False),
                        'seat_number': visit_vals.get('seat_number', False),
                        'flight_number': visit_vals.get('flight_number', False),
                        'flight_sequence': visit_vals.get('flight_sequence', False),
                        'flight_from': visit_vals.get('flight_from', False),
                        'flight_to': visit_vals.get('flight_to', False),
                        'flight_date': visit_vals.get('flight_date', False),
                        'ticket': visit_vals.get('ticket', False),
                        'fqtv': visit_vals.get('fqtv', False),
                        'notes': visit_vals.get('notes', False),
                    })
                    request.env.cr.commit()
                    result_entry.update({'status': 'created', 'visit_id': new_visit.id})
                except Exception as e:
                    result_entry.update({'status': 'error', 'message': str(e)})

                results.append(result_entry)

            return {'ok': True, 'results': results}

        except Exception as e:
            return {'code': 500, 'ok': False, 'message': f"Something went wrong: {str(e)}"}

    @http.route('/lms/api/visits/get', type='json', auth='bearer', methods=['GET', 'POST', ],
                csrf=False, cors='*')
    def get_visits(self, **kw):
        """ Retrieve visit details, including passenger lines."""
        try:
            vals = _json_body(**kw)
            order_by = vals.get('order_by', 'id')
            model = request.env['lms.visit']
            if order_by not in model._fields:
                _logger.warning("Invalid order_by field '%s', defaulting to 'id'", order_by)
                order_by = 'id'

            order_direction = vals.get('order_direction', 'desc').lower()
            if order_direction not in ['asc', 'desc']:
                _logger.warning("Invalid order_direction '%s', defaulting to 'desc'", order_direction)
                order_direction = 'desc'

            order = f"{order_by} {order_direction}"
            model = request.env['lms.visit']
            # domain = vals.get('domain', [])
            domain = [('type', '=', 'main')]
            visits, pagination = _paged(model, domain, order)
            results = [_visit_dict(visit) for visit in visits]
            return {'code': 200, 'data': results, 'pagination': pagination}
        except Exception as e:
            _logger.error("get_visits error: %s", e)
            return {'code': 500, 'message': str(e), 'data': []}
