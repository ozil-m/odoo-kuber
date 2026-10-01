# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json
import logging
from .catalog import _product_dict
from .tools import _json_body

_logger = logging.getLogger(__name__)


# ------------------------------
# Helpers (timezone, casting)
# ------------------------------



def _int_or_none(v):
    """Try to cast to int; return None on failure."""
    try:
        return int(v)
    except Exception:
        return None


def m2o(obj, name_field='display_name'):
    """Normalize Many2one to {id, name} (or False)."""
    return {'id': obj.id, 'name': getattr(obj, name_field, obj.name)} if obj else False


def get_voucher_info(record):
    """
    Shape a voucher into a JSON-safe dict for clients.
    - Normalize Many2one fields to {id, name}
    - Recompute live quantities from cache
    - Expose a print URL only for non-draft/non-canceled records
    """
    # Ensure computed/related fields are fresh (quantities & state)
    record._invalidate_cache(['quantity', 'used_quantity', 'remain_quantity', 'state'], [record.id])

    return {
        'id': record.id,
        'sequence': record.sequence,
        'create_date': record.create_date and record.create_date.isoformat() or None,
        'state': record.state,
        'client_id': m2o(record.client_id),
        'partner': record.partner if record.partner else None,  # assuming Char field (keep as-is)
        'email': record.email if record.email else None,
        'mobile': record.mobile if record.mobile else None,
        'boarding': record.boarding if record.boarding else None,
        'flight_number': record.flight_number if record.flight_number else None,
        'origin': record.origin if record.origin else None,
        'destination': record.destination if record.destination else None,
        'departure_date': record.departure_date and record.departure_date.isoformat() or None,
        'used_on': record.used_on and record.used_on.isoformat() or None,
        'lounge_id': m2o(record.branch_id.lounge_id) if record.branch_id and record.branch_id.lounge_id else None,
        'branch_id': m2o(record.branch_id) if record.branch_id else None,
        'product_id': _product_dict(record.product_id),
        'quantity': int(record.quantity or 0),
        'used_quantity': int(record.used_quantity or 0),
        'remain_quantity': int(record.remain_quantity or 0),
    }


class LoungeElectronicVoucher(http.Controller):

    @http.route(['/lms/voucher/check'], type='json', auth='bearer', methods=["GET", "POST"],
                csrf=False, cors='*')
    def voucher_check(self, **kw):
        """
        Return vouchers created by the current user (or a specific one if voucher_id provided).
        Query params (JSON): {voucher_id?}
        """
        try:
            payload = _json_body(**kw)
            sequence = payload.get('sequence', False)
            if not sequence:
                return {'code': 400, 'message': 'Missing required field: sequence'}
            domain = [('sequence', '=', str(sequence))]
            voucher = request.env['lounge.voucher'].sudo().search(domain)
            if not voucher:
                return {'code': 404, 'message': 'No vouchers found'}
            return {'code': 200, 'data': get_voucher_info(voucher)}
        except Exception as e:
            _logger.error("voucher_read error: %s", e)
            return {'code': 500, 'message': str(e)}

    @http.route(['/voucher/read'], type='json', auth='bearer', methods=["GET", "POST"], csrf=False, cors='*')
    def voucher_read(self, voucher_id=None):
        """
        Return vouchers created by the current user (or a specific one if voucher_id provided).
        Query params (JSON): {voucher_id?}
        """
        try:
            domain = []
            vid = _int_or_none(voucher_id)
            if vid:
                domain.append(('id', '=', vid))
            vouchers = request.env['lounge.voucher'].sudo().search(domain)
            if voucher_id and not vouchers:
                return {'code': 404, 'message': 'No vouchers found'}
            return {'code': 200, 'data': [get_voucher_info(v) for v in vouchers]}
        except Exception as e:
            _logger.error("voucher_read error: %s", e)
            return {'code': 500, 'message': str(e)}

    @http.route(['/voucher/create'], type='json', auth='bearer', methods=["POST"], csrf=False, cors='*')
    def voucher_create(self, **kwargs):
        """
        Create a new voucher; supports optional 'quantity'.
        Body (JSON) must include:
          partner, email, mobile,  flight_number, origin, destination, departure_date
        Optionals:
           boarding, quantity
        """
        try:
            required_fields = ['partner', 'email', 'mobile', 'flight_number', 'origin', 'destination', 'departure_date']
            for f in required_fields:
                if f not in kwargs or not kwargs[f]:
                    return {'code': 400, 'message': f'Missing required field: {f}'}

            # Product resolution from system parameter
            product_param = request.env['ir.config_parameter'].sudo().get_param("voucher_product_id")
            product_id = _int_or_none(product_param)
            if not product_id:
                return {'code': 400, 'message': 'Missing system parameter: voucher_product_id'}
            vals = {
                'partner': kwargs.get('partner'),
                'product_id': product_id,
                'email': kwargs.get('email'),
                'mobile': kwargs.get('mobile'),
                'boarding': kwargs.get('boarding') or False,
                'flight_number': kwargs.get('flight_number'),
                'origin': kwargs.get('origin'),
                'destination': kwargs.get('destination'),
                'departure_date': kwargs.get('departure_date'),
                'quantity': 1,
                'source': "Portal",
            }

            voucher = request.env['lounge.voucher'].with_context(voucher_autocreate=True).sudo().create(vals)
            return {'code': 200, 'data': get_voucher_info(voucher)}
        except Exception as e:
            _logger.error("voucher_create error: %s", e)
            return {'code': 500, 'message': str(e)}

    @http.route(['/voucher/update'], type='json', auth='bearer', methods=["POST"], csrf=False, cors='*')
    def voucher_update(self, voucher_id, **kwargs):
        """
        Update an existing voucher (including quantity).
        Body (JSON): {voucher_id, ...fields}
        """
        try:
            vid = _int_or_none(voucher_id)
            if not vid:
                return {'code': 400, 'message': 'Invalid voucher_id'}
            voucher = request.env['lounge.voucher'].sudo().browse(vid)
            if not voucher.exists():
                return {'code': 404, 'message': 'Voucher not found'}

            editable = ['partner', 'email', 'mobile', 'boarding', 'flight_number', 'origin', 'destination',
                        'departure_date']
            vals = {}
            for f in editable:
                if f in kwargs and kwargs[f]:
                    vals[f] = kwargs[f]

            if not vals:
                return {'code': 400, 'message': 'No valid fields to update'}

            voucher.write(vals)
            voucher._invalidate_cache(['quantity', 'used_quantity', 'remain_quantity', 'state'], [voucher.id])
            return {'code': 200, 'data': get_voucher_info(voucher)}
        except Exception as e:
            _logger.error("voucher_update error: %s", e)
            return {'code': 500, 'message': str(e)}

    @http.route(['/voucher/action'], type='json', auth='bearer', methods=["POST"], csrf=False, cors='*')
    def voucher_action(self, voucher_id, action):
        """
        Run an action on a voucher: confirm / cancel / send_email.
        Body (JSON): {voucher_id, action}
        """
        try:
            if action not in ['confirm', 'cancel', 'send_email']:
                return {'code': 400, 'message': 'Invalid action specified'}
            vid = _int_or_none(voucher_id)
            if not vid:
                return {'code': 400, 'message': 'Invalid voucher_id'}
            voucher = request.env['lounge.voucher'].sudo().browse(vid)
            if not voucher.exists():
                return {'code': 404, 'message': 'Voucher not found'}

            method_name = f'action_{action}'
            if hasattr(voucher, method_name):
                getattr(voucher, method_name)()
                return {'code': 200}
            return {'code': 400, 'message': f'Method {method_name} not available'}
        except Exception as e:
            _logger.error("voucher_action error: %s", e)
            return {'code': 500, 'message': str(e)}
