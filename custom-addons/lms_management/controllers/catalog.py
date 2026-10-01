import logging
from .tools import _json_body, _as_bool, _friendly_cabin, get_base_url, _paged
from collections import defaultdict
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _amenity_dict(l):
    service_map = defaultdict(list)
    for amenity in l.amenity_ids:
        service_map[amenity.service_id].append(
            {"id": amenity.id, "display_name": amenity.display_name, "name": amenity.name, })

    amenities_grouped = []
    for service, capsules in service_map.items():
        if service:
            amenities_grouped.append({
                "service_id": service.id,
                "name": service.name,
                "price": service.price,
                "product_id": service.product_id and {"id": service.product_id.id,
                                                      "name": service.product_id.display_name} or None,
                "capsules": capsules
            })
    return amenities_grouped


def _lounge_dict(l, expand=False):
    product_id = request.env['ir.config_parameter'].sudo().get_param("lounge_access_product_id")
    product = request.env['product.product'].sudo().browse(int(product_id))

    data = {
        "id": l.id,
        "name": l.name,
        "code": l.code,
        "logo": f"{get_base_url()}/web/content/{l.logo.id}" if l.logo and l.logo.public else "",
        "timezone": l.timezone,
        "branch_id": {'id': l.branch_id.id, 'name': l.branch_id.name} if l.branch_id else None,
        "cash_product": {'id': product.id, 'name': product.name,
                         'price': l.pricelist_id._get_product_price(product, 1.0, )} if product else None,
        "partner_id": int(request.env['ir.config_parameter'].sudo().get_param("cash_partner_id")) or None,
        "amenities": _amenity_dict(l),
    }

    return data


def _product_dict(p, lounge=None):
    """ Return product dictionary with price computed for the given lounge pricelist.
     if lounge is None, price values are zeroed out."""
    if not lounge:
        amount_vals = {
            "total_excluded": 0.0,
            "tax": p.taxes_id[0].name,
            "tax_amount": 0.0,
            "total_included": 0.0,
        }
    else:

        amount_tax_vals = p.taxes_id[0].compute_all(lounge.pricelist_id._get_product_price(p, 1.0, ))
        amount_vals = {
            "total_excluded": amount_tax_vals['total_excluded'],
            "tax": p.taxes_id[0].name,
            "tax_amount": amount_tax_vals['total_included'] - amount_tax_vals['total_excluded'],
            "total_included": amount_tax_vals['total_included'],
        }
    return {
        "id": p.id,
        "name": p.name,
        "display_name": p.display_name,
        "price": amount_vals,
    }


def _airline_dict(r, lounge):
    data = {
        "id": r.id,
        "name": r.name,
        "code": r.code,
        "logo": f"{get_base_url()}/web/content/{r.logo.id}" if r.logo and r.logo.public else "",
        "before_departure_window": r.before_departure_window,
        "after_arrival_window": r.after_arrival_window,
        "contract": {
            "start": r.contract_start and r.contract_start.isoformat() or None,
            "end": r.contract_end and r.contract_end.isoformat() or None,
            "status": r.contract_status or None,
        },
        "pax_quota": r.pax_quota,
        "free_pax_quota": r.free_pax_quota,
        "quota": {
            "used": r.used_quota,
            "remaining": r.remaining_quota,
            "start": r.quota_start and r.quota_start.isoformat() or None,
            "end": r.quota_end and r.quota_end.isoformat() or None,
            "allow_access_after_quota_exceeded": r.allow_access_after_quota_exceeded,
        },
        "allowed_access_rule": r.allowed_access_rule,  # "booking" | "ffp" | "both"
        "partner_id": r.partner_id and r.partner_id.id or None,
        # "lounges": [{"id": l.lounge_id.id, "name": l.lounge_id.name} for l in r.lounge_ids],
    }

    rule = (r.allowed_access_rule or "both").lower()
    # Include Booking Class rules if airline allows "booking" or "both"
    if rule in ("booking", "both"):
        data["booking_rules"] = [{
            "id": br.id,
            # "display_name": br.display_name,
            "logo": f"{get_base_url()}/web/content/{br.logo.id}" if br.logo and br.logo.public else "",
            "name": br.display_name,
            "cabin_class": br.cabin_class or None,
            "cabin_name": br.cabin_class and _friendly_cabin(br.cabin_class) or None,
            "booking_class_letters": br.code or None,
            "eligible": br.eligible,
            "product_main_id": (br.product_main_id and _product_dict(br.product_main_id)) or None,
            "allow_guest": br.allow_guest,
            "guest_count": br.guest_count,
            "product_guest_id": (br.product_guest_id and _product_dict(br.product_guest_id)) or None,
            "rank": br.rank,
            "notes": br.notes or None,
            # "lounge_ids": br.lounge_ids and [{'id': lounge.id, 'name': lounge.name, 'code': lounge.code} for lounge in
            #                                  br.lounge_ids] or None,
        } for br in r.booking_class_acceptance_rules_ids if br.eligible]

    # Include FFP acceptances if airline allows "ffp" or "both"
    if rule in ("ffp", "both"):
        data["ffp_acceptances"] = [{
            "id": fa.id,
            # "display_name": fa.display_name,
            "logo": f"{get_base_url()}/web/content/{fa.logo.id}" if fa.logo and fa.logo.public else "",
            "name": fa.display_name,
            "ffp_program": fa.ffp_program_id and {"id": fa.ffp_program_id.id, "name": fa.ffp_program_id.name,
                                                  "code": fa.ffp_program_id.code} or None,
            "tier": fa.tier_id and {"id": fa.tier_id.id, "name": fa.tier_id.name, "code": fa.tier_id.code} or None,
            "eligible": fa.eligible,
            "product_main_id": fa.product_main_id and _product_dict(fa.product_main_id) or None,
            "allow_guest": fa.allow_guest,
            "guest_count": fa.allow_guest and fa.guest_count or None,
            "product_guest_id": fa.allow_guest and fa.product_guest_id and _product_dict(fa.product_guest_id) or None,
            "validation_expression": fa.validation_expression or None,
            # "lounge_ids": fa.lounge_ids and [{'id': lounge.id, 'name': lounge.name, 'code': lounge.code} for lounge in
            #                                  fa.lounge_ids] or None,
            "notes": fa.notes or None,
        } for fa in r.ffp_tier_acceptance_rules_ids if fa.eligible]

    return data


def _aggregator_dict(a, lounge):
    # :contentReference[oaicite:2]{index=2}
    return {
        "id": a.id,
        "name": a.name,
        "code": a.code,
        "logo": f"{get_base_url()}/web/content/{a.logo.id}" if a.logo and a.logo.public else "",
        "contract": {
            "start": a.contract_start and a.contract_start.isoformat() or None,
            "end": a.contract_end and a.contract_end.isoformat() or None,
            "status": a.contract_status or None,
        },
        "settlement_model": a.settlement_model,
        "pax_quota": a.pax_quota,
        "free_pax_quota": a.free_pax_quota,
        "quota": {
            "used": a.used_quota,
            "remaining": a.remaining_quota,
            "start": a.quota_start and a.quota_start.isoformat() or None,
            "end": a.quota_end and a.quota_end.isoformat() or None,
            "allow_access_after_quota_exceeded": a.allow_access_after_quota_exceeded,
        },
        "allow_integration": a.allow_integration,
        # "api": {"base_url": a.api_base_url or None, "api_key": bool(a.api_key) or None},
        "partner_id": a.partner_id and a.partner_id.id or None,
        "acceptance_rule": [{"id": rule.id,
                             # "display_name": fa.display_name,
                             "name": rule.display_name,
                             "logo": f"{get_base_url()}/web/content/{rule.logo.id}" if rule.logo and rule.logo.public else "",
                             "eligible": rule.eligible,
                             "product_main_id": rule.product_main_id and _product_dict(rule.product_main_id) or None,
                             "allow_guest": rule.allow_guest,
                             "guest_count": rule.allow_guest and rule.guest_count or None,
                             "product_guest_id": rule.allow_guest and rule.product_guest_id and _product_dict(
                                 rule.product_guest_id) or None,
                             "validation_expression": rule.validation_expression or None,
                             "notes": rule.notes or None, } for rule in a.business_partner_acceptance_rules_ids if
                            rule.eligible],
    }


def _corporate_dict(c, lounge):
    # :contentReference[oaicite:4]{index=4}
    return {
        "id": c.id,
        "name": c.name,
        "code": c.code,
        "logo": f"{get_base_url()}/web/content/{c.logo.id}" if c.logo and c.logo.public else "",
        "contract": {
            "start": c.contract_start and c.contract_start.isoformat() or None,
            "end": c.contract_end and c.contract_end.isoformat() or None,
            "status": c.contract_status,
        },
        "settlement_model": c.settlement_model,
        "pax_quota": c.pax_quota,
        "free_pax_quota": c.free_pax_quota,
        "quota": {
            "used": c.used_quota,
            "remaining": c.remaining_quota,
            "start": c.quota_start and c.quota_start.isoformat() or None,
            "end": c.quota_end and c.quota_end.isoformat() or None,
            "allow_access_after_quota_exceeded": c.allow_access_after_quota_exceeded,
        },
        "allow_integration": c.allow_integration,
        # "api": {"base_url": c.api_base_url or None, "api_key": bool(c.api_key) or None},
        "partner_id": c.partner_id and c.partner_id.id or None,
        "acceptance_rule": [{"id": rule.id,
                             # "display_name": fc.display_name,
                             "name": rule.display_name,
                             "logo": f"{get_base_url()}/web/content/{rule.logo.id}" if rule.logo and rule.logo.public else "",
                             "eligible": rule.eligible,
                             "product_main_id": rule.product_main_id and _product_dict(rule.product_main_id,
                                                                                       lounge) or None,
                             "allow_guest": rule.allow_guest,
                             "guest_count": rule.allow_guest and rule.guest_count or None,
                             "product_guest_id": rule.allow_guest and rule.product_guest_id and _product_dict(
                                 rule.product_guest_id, lounge) or None,
                             "validation_expression": rule.validation_expression or None,
                             "notes": rule.notes or None, } for rule in c.business_partner_acceptance_rules_ids if
                            rule.eligible],
    }


def _cash_dict(c, lounge):
    # :contentReference[oaicite:4]{index=4}
    return {
        "id": c.id,
        "name": c.name,
        "code": c.code,
        "logo": f"{get_base_url()}/web/content/{c.logo.id}" if c.logo and c.logo.public else "",
        "settlement_model": c.settlement_model,
        "partner_id": c.partner_id and c.partner_id.id or None,
        "acceptance_rule": [{"id": rule.id,
                             # "display_name": fc.display_name,
                             "name": rule.display_name,
                             "logo": f"{get_base_url()}/web/content/{rule.logo.id}" if rule.logo and rule.logo.public else "",
                             "eligible": rule.eligible,
                             "product_main_id": rule.product_main_id and _product_dict(rule.product_main_id,
                                                                                       lounge) or None,
                             "allow_guest": rule.allow_guest,
                             "guest_count": rule.allow_guest and rule.guest_count or None,
                             "product_guest_id": rule.allow_guest and rule.product_guest_id and _product_dict(
                                 rule.product_guest_id, lounge) or None,
                             "validation_expression": rule.validation_expression or None,
                             "notes": rule.notes or None, } for rule in c.business_partner_acceptance_rules_ids if
                            rule.eligible],
    }


def _ffp_program_dict(p):
    # :contentReference[oaicite:5]{index=5}
    return {
        "id": p.id,
        "name": p.name,
        "code": p.code,
        "logo": f"{get_base_url()}/web/content/{p.logo.id}" if p.logo and p.logo.public else "",
        "issuer_airlines": p.business_partner_ids and [{"id": airline.id,
                                                        "name": airline.name} for airline in
                                                       p.business_partner_ids] or None,
    }


def _ffp_tier_dict(t):
    return {
        "id": t.id,
        "name": t.name,
        "code": t.code,
        "logo": f"{get_base_url()}/web/content/{t.logo.id}" if t.logo and t.logo.public else "",
        "rank": t.rank,
    }


def _business_partner_dict(records, lounge):
    aggregators = records.filtered(lambda record: record.partner_type == 'aggregator')
    corporates = records.filtered(lambda record: record.partner_type == 'corporate')
    airlines = records.filtered(lambda record: record.partner_type == 'airline')
    records = records.filtered(lambda record: record.partner_type == 'cash')
    return {
        "airlines": [_airline_dict(airline, lounge) for airline in airlines],
        "aggregators": [_aggregator_dict(aggregator, lounge) for aggregator in aggregators],
        "corporates": [_corporate_dict(corporate, lounge) for corporate in corporates],
        "cash": [_cash_dict(record, lounge) for record in records],
    }


# -------------------------------------------------
# Configuration LMS API (read-only: airlines, lounges, amenities, aggregators, corporates, bookings, FFP)
# -------------------------------------------------
class LmsCatalogApiController(http.Controller):

    # ---------- endpoints: Airlines ----------
    @http.route('/lms/api/business_partner', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def business_partner_list(self, **kw):
        """ List business_partner, optionally expanded with booking rules and FFP acceptance rules."""
        vals = _json_body(**kw)
        lounge_id = vals.get("lounge_id")
        if not lounge_id:
            return {'code': 400, 'message': 'lounge_id is required.'}
        lounge = request.env["lms.lounge"].browse(int(lounge_id))
        if not lounge.exists():
            return {'code': 400, 'message': 'Invalid lounge_id provided.'}

        try:
            acceptance_rules = request.env['acceptance.rule'].search(
                ['|', ('lounge_ids', 'in', lounge.id), ('lounge_ids', '=', False)])
            eligible_acceptance_rules = acceptance_rules.filtered(
                lambda record: record.eligible and record.product_main_id)
            partners = request.env['business.partner'].browse(
                list(set(eligible_acceptance_rules.mapped('business_partner_id').ids)))
            result = _business_partner_dict(partners, lounge)
            pagination = {
                "current_page": 1,
                "next_page": None,
                "previous_page": None,
                "total_pages": 1,
                "per_page": len(partners),
                "total_entries": len(partners),
            }
            return {'code': 200, 'data': result, 'pagination': pagination}
        except Exception as e:
            _logger.error("business_partner_list error: %s", e)
            return {'code': 500, 'message': str(e)}

    # ---------- endpoints: Airlines ----------
    @http.route('/lms/api/airlines', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def airlines_list(self, **kw):
        """ List airlines, optionally expanded with booking rules and FFP acceptance rules."""
        try:
            model = request.env["business.partner"]
            recs, pagination = _paged(model, [('partner_type', '=', 'airline')])
            expand = _as_bool(_json_body().get("expand"))
            result = [_airline_dict(r, expand) for r in recs]
            return {'code': 200, 'data': result, 'pagination': pagination}
        except Exception as e:
            _logger.error("airlines_list error: %s", e)
            return {'code': 500, 'message': str(e)}

    # ---------- endpoints: Lounges ----------
    @http.route('/lms/api/lounges', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def lounges_list(self, **kw):
        """ List lounges, optionally expanded with amenities."""
        try:
            model = request.env["lms.lounge"]
            recs, pagination = _paged(model, [])
            expand = _as_bool(_json_body().get("expand"))
            result = [_lounge_dict(r, expand) for r in recs]
            return {'code': 200, 'data': result, 'pagination': pagination}
        except Exception as e:
            _logger.error("lounges_list error: %s", e)
            return {'code': 500, 'message': str(e)}

    # ---------- endpoints: Aggregators ----------
    @http.route('/lms/api/aggregators', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def aggregators_list(self, **kw):
        """ List aggregators."""
        try:
            model = request.env["business.partner"]
            recs, pagination = _paged(model, [('partner_type', '=', 'aggregator')])
            result = [_aggregator_dict(r) for r in recs]
            return {'code': 200, 'data': result, 'pagination': pagination}
        except Exception as e:
            _logger.error("aggregators_list error: %s", e)
            return {'code': 500, 'message': str(e)}

    # ---------- endpoints: Corporates ----------
    @http.route('/lms/api/corporates', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def corporates_list(self, **kw):
        """ List corporates."""
        try:
            model = request.env["business.partner"]
            recs, pagination = _paged(model, [('partner_type', '=', 'corporate')])
            result = [_corporate_dict(r) for r in recs]
            return {'code': 200, 'data': result, 'pagination': pagination}
        except Exception as e:
            _logger.error("corporates_list error: %s", e)
            return {'code': 500, 'message': str(e)}

    # ---------- endpoints: FFP ----------
    @http.route('/lms/api/ffp/programs', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def ffp_programs_list(self, **kw):
        """ List FFP programs."""
        try:
            model = request.env["lms.ffp.program"]
            recs, pagination = _paged(model, [])
            result = [_ffp_program_dict(r) for r in recs]
            return {'code': 200, 'data': result, 'pagination': pagination}
        except Exception as e:
            _logger.error("ffp_programs_list error: %s", e)
            return {'code': 500, 'message': str(e)}

    @http.route('/lms/api/ffp/tiers', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def ffp_tiers_list(self, **kw):
        """ List FFP tiers."""
        try:
            model = request.env["lms.ffp.tier"]
            recs, pagination = _paged(model, [])
            result = [_ffp_tier_dict(r) for r in recs]
            return {'code': 200, 'data': result, 'pagination': pagination}
        except Exception as e:
            _logger.error("ffp_tiers_list error: %s", e)
            return {'code': 500, 'message': str(e)}

    # ---------- endpoints: Amenities ----------
    @http.route('/lms/api/amenities', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def amenities_list(self, **kw):
        """ List amenities."""
        try:
            model = request.env["lms.amenity"]
            recs, pagination = _paged(model, [])
            result = [_amenity_dict(r) for r in recs]
            return {'code': 200, 'data': result, 'pagination': pagination}
        except Exception as e:
            _logger.error("amenities_list error: %s", e)
            return {'code': 500, 'message': str(e)}
