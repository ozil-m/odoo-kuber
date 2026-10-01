from odoo.http import request
import json
import logging
_logger = logging.getLogger(__name__)

def attachment_read(visit_id):
    """ Get attachment list by visit ID"""
    result = []
    base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
    model = 'lms.visit'
    try:
        attachment = request.env['ir.attachment']
        attachment_ids = attachment.search(
            [('res_model', '=', model), ('res_id', '=', visit_id)])
        if attachment_ids:
            for attach in attachment_ids:
                if attach.public and base_url:
                    url = f"{base_url}/web/content/{attach.id}"
                    result.append(
                        {
                            'id': attach.id,
                            'name': attach.name,
                            'create_by': {'id': attach.create_uid.id,
                                          'name': attach.create_uid.name} if attach.create_uid else None,
                            "create_date": attach.create_date and attach.create_date.isoformat() or None,
                            'url': url,
                        }
                    )

        return result
    except Exception as e:
        _logger.error(f"Error in attachment_read: {e}")
        return None


def get_base_url():
    """ Return the base URL of the Odoo instance."""
    return request.env['ir.config_parameter'].sudo().get_param('web.base.url')


def _json_body(**kw):
    """Return request JSON as dict; unwrap JSON-RPC 'params' and tolerate strings."""
    if kw:
        return kw.get("params", kw)
    jr = getattr(request, "jsonrequest", None)
    if isinstance(jr, dict):
        return jr.get("params", jr)
    if isinstance(jr, str):
        try:
            data = json.loads(jr);  return data.get("params", data) if isinstance(data, dict) else {}
        except Exception:
            pass
    data = request.httprequest.get_json(silent=True)
    if isinstance(data, dict):
        return data.get("params", data)
    if isinstance(data, str):
        try:
            data = json.loads(data);  return data.get("params", data) if isinstance(data, dict) else {}
        except Exception:
            pass
    try:
        raw = request.httprequest.data
        if raw:
            data = json.loads(raw.decode("utf-8"))
            return data.get("params", data) if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _as_bool(v):
    if isinstance(v, bool): return v
    if isinstance(v, str): return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")
    return bool(v)


def _friendly_cabin(code: str):
    return {"F": "First", "J": "Business", "W": "Premium", "Y": "Economy"}.get((code or "").upper(),
                                                                               (code or "").upper())


def translate_selection(record, field_name, force_value=None):
    """ Translate a selection field value to its label."""
    value = force_value or record[field_name]
    return dict(record._fields[field_name]._description_selection(record.env)).get(value)


def _paged(model, domain, order="id desc"):
    params = _json_body()
    limit = int(params.get("limit") or False)
    page = int(params.get("page") or 1)
    offset = (page - 1) * limit if page > 0 else 0
    q = (params.get("q") or "").strip()
    if q:
        # basic ilike on name/code fields
        if "code" in model._fields:
            domain = ['|', ("name", "ilike", q), ("code", "ilike", q)] + (domain or [])
        else:
            domain = [("name", "ilike", q)] + (domain or [])
    recs = model.sudo().search(domain or [], limit=limit, offset=offset, order=order)
    # Get total count for pagination
    total_entries = model.sudo().search_count(domain or [])
    # Compute pagination info
    current_page = (offset // limit) + 1 if limit else 1
    total_pages = (total_entries + limit - 1) // limit if limit else 1
    next_page = current_page + 1 if current_page < total_pages else None
    previous_page = current_page - 1 if current_page > 1 else None

    pagination = {
        "current_page": current_page,
        "next_page": next_page,
        "previous_page": previous_page,
        "total_pages": total_pages,
        "per_page": limit,
        "total_entries": total_entries,
    }
    return recs, pagination
