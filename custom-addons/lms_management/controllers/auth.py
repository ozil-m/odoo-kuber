# controllers/main.py
from odoo import http, _, fields
from odoo.http import request
from dateutil.relativedelta import relativedelta
from odoo.exceptions import AccessDenied
from odoo.addons.lms_management.models.business.utils_bcbp import parse_bcbp, convert_julian_to_date
from passlib.context import CryptContext  # <-- use passlib directly
import logging
import secrets

_logger = logging.getLogger(__name__)
_PWD_CTX = CryptContext(schemes=["pbkdf2_sha512", "bcrypt", "sha512_crypt", "plaintext"], deprecated="auto")
from .tools import _json_body, get_base_url


# -------------------------------------------------
# Auth controller: login/issue/renew keys + whoami
# -------------------------------------------------
def _apikey_sql_introspect():
    """
    Return (table, secret_cols, exp_col) for res.users.apikeys by inspecting the DB.

    secret_cols: non-ORM char/text columns long enough for a hash
                 (TEXT, or VARCHAR with length >= 60, or VARCHAR with NULL maxlen = unlimited).
    exp_col:     one non-ORM date/datetime column if present (best guess).
    """
    Apikeys = request.env["res.users.apikeys"]
    table = Apikeys._table or "res_users_apikeys"

    cr = request.env.cr
    cr.execute("""
        SELECT column_name, data_type, character_maximum_length
          FROM information_schema.columns
         WHERE table_name = %s
           AND table_schema = current_schema()
    """, (table,))
    cols = cr.fetchall()  # [(name, type, maxlen), ...]

    known = set(Apikeys._fields.keys()) | {
        "id", "display_name", "create_date", "create_uid", "write_date", "write_uid"
    }

    text_types = {"character varying", "text", "varchar"}

    def is_long_enough(dtype, maxlen, name):
        """ Check if a column is long enough to hold a hashed secret.
        """
        if name == "index":  # your schema has varchar(8) -> never use it
            return False
        if dtype == "text":
            return True
        if dtype in ("character varying", "varchar"):
            # None means unlimited in PG → treat as long enough
            return (maxlen is None) or (maxlen >= 60)
        return False

    raw_secret_candidates = [
        (name, dtype, maxlen)
        for (name, dtype, maxlen) in cols
        if dtype in text_types and name not in known and is_long_enough(dtype, maxlen, name)
    ]

    hints = ["key", "token", "digest", "hash", "secret", "value"]

    def rank_secret(row):
        """ Rank secret candidates:
        1) hinted names first (key/token/secret/digest/hash/value)
        2) longer maxlen first
        """
        name, dtype, maxlen = row
        low = name.lower()
        hinted = any(h in low for h in hints)
        eff_len = (10 ** 6 if dtype == "text" else (10 ** 6 if maxlen is None else maxlen))
        return (0 if hinted else 1, -eff_len, len(name))

    secret_cols = [name for (name, _, _) in sorted(raw_secret_candidates, key=rank_secret)]

    # expiration candidates: any non-ORM date/datetime column
    dt_types = {"timestamp without time zone", "timestamp with time zone", "date"}
    raw_exp_candidates = [
        (name, dtype)
        for (name, dtype, _maxlen) in cols
        if dtype in dt_types and name not in known
    ]

    def rank_exp(row):
        """ Rank expiration candidates:
        1) hinted names first (expir/valid/until/expiry/expire)
        2) shorter names first
        """
        name, _ = row
        low = name.lower()
        hinted = any(s in low for s in ["expir", "valid", "until", "expiry", "expire"])
        return (0 if hinted else 1, len(name))

    exp_col = sorted(raw_exp_candidates, key=rank_exp)[0][0] if raw_exp_candidates else None

    return table, secret_cols, exp_col


def _extract_plaintext_key(res):
    """
    Extract plaintext API key from various return shapes:
    - direct string
    - action dict with context['default_key'] / ['api_key'] / ['key']
    - action dict pointing to a wizard record (res.users.apikeys.show) -> read its `key`
    """
    # 1) Already a string?
    if isinstance(res, str) and res:
        return res

    if not isinstance(res, dict):
        return None

    # 2) Check action context first (most common)
    ctx = res.get("context") or {}
    for k in ("default_key", "api_key", "key"):
        if ctx.get(k):
            return ctx[k]

    # 3) If it's a wizard action, read the wizard record to fetch the plaintext
    res_model = res.get("res_model")
    res_id = res.get("res_id")
    wizard_models = [
        "res.users.apikeys.show",
        "res.users.apikeys.show.wizard",  # be generous for forks
        "res.users.apikeys.wizard",
    ]
    if res_model in wizard_models and res_id:
        try:
            wiz = request.env[res_model].sudo().browse(int(res_id))
            if wiz and wiz.exists():
                for fld in ("key", "api_key", "default_key"):
                    if hasattr(wiz, fld):
                        val = getattr(wiz, fld)
                        if val:
                            return val
        except Exception:
            pass

    # 4) Fallback: try to find the most recent wizard (just in case res_id is missing)
    try:
        for m in wizard_models:
            if m in request.env:
                wiz = request.env[m].sudo().search([], order="id desc", limit=1)
                if wiz and hasattr(wiz, "key") and wiz.key:
                    return wiz.key
    except Exception:
        pass

    return None


def _get_api_key_ttl_days():
    try:
        val = request.env['ir.config_parameter'].sudo().get_param('lms.api_key_ttl_days')
        return int(val) if val else 1
    except Exception:
        return 1


def _verify_password_via_db(user_id: int, password: str) -> bool:
    """Bypass fragile hooks: read the hash via SQL and verify with passlib."""
    cr = request.env.cr
    cr.execute("SELECT password FROM res_users WHERE id=%s", (user_id,))
    row = cr.fetchone()
    hashed = (row and row[0]) or ""
    return bool(hashed) and _PWD_CTX.verify(password, hashed)


def _find_existing_key(user):
    Apikeys = request.env["res.users.apikeys"].sudo()
    return Apikeys.search([("user_id", "=", user.id)], order="create_date desc, id desc", limit=1) or False


def _gen_api_key_for_user(user, name=None):
    """
    Generate a fresh API key and return PLAINTEXT once.
    - Try official Odoo paths first (user._generate_api_key, record methods).
    - If they don't surface plaintext, reuse the SAME record and write the digest
      (ORM or SQL) + expiration + index, then verify the digest before returning.
    """
    user = user.sudo()
    if not name:
        when = (fields.Datetime.now() or fields.Datetime.now()).strftime("%Y-%m-%d %H:%M")
        name = f"LMS API Key ({when})"

    Apikeys = request.env["res.users.apikeys"].sudo()

    # single record we will reuse for action-based or manual fallback → avoids duplicates
    rec = Apikeys.create({"user_id": user.id, "name": name, "scope": "rpc"})

    # ---- A) Official user-level helper (string OR action) ----
    if hasattr(user, "_generate_api_key"):
        for args in ((name,), (), ("",)):
            try:
                res = user._generate_api_key(*args)
                k = _extract_plaintext_key(res)
                if k:
                    return k
            except TypeError:
                continue
            except Exception:
                pass

    # ---- B) Official record-level helpers on the SAME record ----
    for meth in ("action_generate", "action_generate_key", "generate_api_key", "_generate_api_key"):
        if hasattr(rec, meth):
            try:
                res = getattr(rec, meth)()
                k = _extract_plaintext_key(res)
                if k:
                    return k
            except Exception:
                continue

    # ---- C) Manual fallback on the SAME record (write digest/expiry) ----
    ttl = _get_api_key_ttl_days()
    plaintext = secrets.token_urlsafe(30)  # ~240 bits entropy
    digest = _PWD_CTX.hash(plaintext)
    expiry_dt = fields.Datetime.now() + relativedelta(days=ttl)

    # Prefer ORM-visible fields when present
    hash_field, exp_field = _apikey_field_names()
    if hash_field:
        rec.sudo().write({hash_field: digest})
        if exp_field:
            rec.sudo().write({exp_field: expiry_dt})
    else:
        # Hidden digest → write to ALL viable secret cols (includes 'key')
        table, secret_cols, exp_col = _apikey_sql_introspect()
        if not secret_cols:
            raise Exception(f"Cannot locate any secret digest column on table {table}; please share table schema.")
        cr = request.env.cr
        for col in secret_cols:
            cr.execute(f'UPDATE "{table}" SET "{col}"=%s WHERE id=%s', (digest, rec.id))
        if exp_field:
            rec.sudo().write({exp_field: expiry_dt})
        elif exp_col:
            cr.execute(f'UPDATE "{table}" SET "{exp_col}"=%s WHERE id=%s', (expiry_dt, rec.id))

    # ---- C.1) Write the 8-char index used by bearer auth lookup ----
    try:
        idx = (plaintext or "")[:8]
        # If the 'index' field is available on the model, use ORM; otherwise use SQL (quoted).
        if "index" in Apikeys._fields:
            rec.sudo().write({"index": idx})
        else:
            table, _secret_cols, _exp_col = _apikey_sql_introspect()
            cr = request.env.cr
            cr.execute(f'UPDATE "{table}" SET "index"=%s WHERE id=%s', (idx, rec.id))
    except Exception:
        # don't fail key issuance just because index write had an issue
        pass

    # ---- D) Sanity check: read back a digest and verify plaintext ----
    stored = None
    if hash_field:
        stored = getattr(rec.sudo(), hash_field, None)
    if not stored:
        table, secret_cols, _ = _apikey_sql_introspect()
        if secret_cols:
            cr = request.env.cr
            cr.execute(f'SELECT "{secret_cols[0]}" FROM "{table}" WHERE id=%s', (rec.id,))
            row = cr.fetchone()
            stored = row and row[0]

    ctx = None
    if hasattr(Apikeys, "_crypt_context"):
        try:
            ctx = Apikeys._crypt_context()
        except Exception:
            ctx = None
    if not ctx:
        ctx = _PWD_CTX

    if not stored or not ctx.verify(plaintext, stored):
        try:
            rec.unlink()
        except Exception:
            pass
        raise Exception("Sanity check failed: stored digest did not verify.")

    return plaintext


def _apikey_field_names():
    """
    Inspect res.users.apikeys to find:
      - hash_field: where the hashed token is stored (may be None on unusual forks)
      - exp_field:  the expiration field (if any)
    Never raises just because hash field is missing; that would break expiry checks.
    """
    Apikeys = request.env["res.users.apikeys"]
    f = Apikeys._fields
    hash_field = None
    primary_hash = ["key", "digest", "hashed_key", "token", "hash", "api_key", "apikey", "key_hash", "secret",
                    "secret_hash", "value"]
    for h in primary_hash:
        if h in f:
            hash_field = h
            break
    if not hash_field:
        candidates = [
            n for n, fld in f.items()
            if getattr(fld, "type", None) in ("char", "text")
               and n not in ("name", "scope")
               and any(s in n.lower() for s in ["key", "token", "digest", "hash", "secret", "value"])
        ]
        if candidates:
            rank = {n: i for i, n in enumerate(primary_hash)}
            candidates.sort(key=lambda n: rank.get(n, 999))
            hash_field = candidates[0]

    exp_field = None
    primary_exp = ["expiration", "expiration_date", "expires_at", "expire_at", "date_expiration", "valid_until",
                   "expiry", "expire"]
    for e in primary_exp:
        if e in f:
            exp_field = e
            break
    if not exp_field:
        exp_candidates = [
            n for n, fld in f.items()
            if getattr(fld, "type", None) in ("date", "datetime")
               and any(s in n.lower() for s in ["expir", "valid", "until", "expiry", "expire"])
        ]
        if exp_candidates:
            exp_field = exp_candidates[0]

    return hash_field, exp_field


def _is_key_expired(key_rec, ttl_days):
    """Prefer explicit expiration (ORM or SQL); else fallback to create_date + TTL."""
    if not key_rec:
        return True
    _hash, exp_field = _apikey_field_names()
    try:
        # Try ORM field first
        if exp_field and getattr(key_rec, exp_field, None):
            expiry = getattr(key_rec, exp_field)
        else:
            # Try SQL column
            table, _secret_col, exp_col = _apikey_sql_introspect()
            if exp_col:
                cr = request.env.cr
                cr.execute(f'SELECT "{exp_col}" FROM "{table}" WHERE id=%s', (key_rec.id,))
                row = cr.fetchone()
                if row and row[0]:
                    expiry = row[0]
                else:
                    expiry = key_rec.create_date + relativedelta(days=ttl_days)
            else:
                expiry = key_rec.create_date + relativedelta(days=ttl_days)

        return fields.Datetime.now() >= expiry
    except Exception:
        return True


class LmsAuthController(http.Controller):

    @http.route('/lms/api/auth/login_key', type='json', auth='public', methods=['POST', 'GET'], csrf=False,
                cors='*')
    def login_and_issue_key(self, **kw):
        """
        Password-login in the CURRENT DB and return API key info.
          - If an unexpired key exists: status=existing_valid + expires_on (no plaintext).
          - Else (expired/missing) or force_new: revoke/issue NEW key and return plaintext once.
        """
        try:
            body = _json_body(**kw)
            if not isinstance(body, dict):
                return {"code": 400, "data": [], "message": "Bad JSON body (expected object)"}
            # Normalize JSON-RPC envelope so any downstream hook expecting ['params'] is safe.
            try:
                jr = getattr(request, "jsonrequest", None)
                if not (isinstance(jr, dict) and isinstance(jr.get("params"), dict)):
                    request.jsonrequest = {"params": body}
            except Exception:
                pass

            # Always bind to the active DB
            db = request.env.cr.dbname
            try:
                request.session.db = db
            except Exception:
                pass

            login = (body.get("login") or "").strip()
            password = body.get("password") or ""

            if not login or not password:
                return {"code": 400, "data": [], "message": "Missing login/password"}

            # ---- Verify credentials WITHOUT session/auth hooks (no more 'string indices...' explosions) ----
            Users = request.env["res.users"].sudo()
            user = Users.search([("login", "=", login)], limit=1)
            if not user or not user.active:
                return {"code": 401, "data": [], "message": "Invalid credentials", "db_used": db}

            try:
                if not _verify_password_via_db(user.id, password):
                    return {"code": 401, "data": [], "message": "Invalid credentials", "db_used": db}
            except Exception as e:
                return {"code": 401, "data": [], "message": "Authentication failed", "detail": str(e), "db_used": db}

            # ---- Issue or return existing API key ----
            ttl = _get_api_key_ttl_days()

            # Revoke all keys and issue a fresh one (plaintext returned once)
            request.env["res.users.apikeys"].sudo().search([("user_id", "=", user.id)]).unlink()

            # code = body.get("code") or False
            # if user.totp_enabled:
            #     if not code:
            #         return {"code": 401, "data": [], "message": "Missing 2FA code", "db_used": db}
            #     try:
            #         check = user._totp_check(code)
            #
            #         if not check:
            #             return {"code": 401, "data": [], "message": "Invalid 2FA code", "db_used": db}
            #     except AccessDenied as ade:
            #         return {"code": 401, "data": [], "message": str(ade), "db_used": db}
            try:
                api_key = _gen_api_key_for_user(user)
            except Exception as e:
                return {"code": 500, "data": [], "message": f"Something went wrong:{str(e)}"}
            lounge = user.branch_id.lounge_id if user.branch_id and user.branch_id.lounge_id else None
            branch_ids = user.branch_ids or None

            vals = {
                "uid": user.id,
                "name": user.name,
                "permissions": {
                    #     "lms_group_user": user.has_group('lms_management.lms_group_user'),
                    #     "lms_group_supervisor": user.has_group('lms_management.lms_group_supervisor'),
                    #     "lms_group_finance": user.has_group('lms_management.lms_group_finance'),
                    #     "lms_group_manager": user.has_group('lms_management.lms_group_manager'),
                },
                "default_lounge": {"id": lounge.id,
                                   "name": lounge.name,
                                   "code": lounge.branch_id.code,
                                   "state": lounge.state_id.name or None,
                                   "airport": lounge.airport_id.name or None,
                                   "terminal": lounge.terminal_id.name or None,
                                   "logo": f"{get_base_url()}/web/content/{lounge.logo.id}" if lounge.logo and lounge.logo.public else "",
                                   } if lounge else None,
                "allowed_lounges": [{"id": branch.lounge_id.id,
                                     "name": branch.lounge_id.name,
                                     "code": branch.code,
                                     "state": branch.lounge_id.state_id.name or None,
                                     "airport": branch.lounge_id.airport_id.name or None,
                                     "terminal": branch.lounge_id.terminal_id.name or None,
                                     "logo": f"{get_base_url()}/web/content/{branch.lounge_id.logo.id}" if branch.lounge_id.logo and branch.lounge_id.logo.public else "", }
                                    for branch in branch_ids if
                                    branch.lounge_id] if user.branch_ids else None,
                "api_key": api_key,  # PLAINTEXT once
                "status": "new_issued",
                "ttl_days": ttl,
                "note": "Store this key safely; it will not be shown again.", }
            return {"code": 200, "data": vals, "message": "New API key issued.", }
        except Exception as e:
            _logger.error(f"Error in /lms/api/auth/login_key: {str(e)}")
            return {"code": 500, "data": [], "message": f"Internal server error: {str(e)}"}

    @http.route('/lms/api/auth/new_key', type='json', auth='bearer', methods=['POST'], csrf=False,
                cors='*')
    def new_key(self, **kw):
        """Rotate and return a fresh API key for the current user (revoke ALL old keys)."""
        try:
            user = request.env.user.sudo()
            request.env["res.users.apikeys"].sudo().search([("user_id", "=", user.id)]).unlink()
            api_key = _gen_api_key_for_user(user)
            ttl = _get_api_key_ttl_days()
            vals = {
                "uid": user.id,
                "name": user.name,
                "status": "new_issued",
                "ttl_days": ttl,
                "api_key": api_key,  # PLAINTEXT once
                "note": "Store this key safely; it will not be shown again.", }
            return {"code": 200, "data": vals}
        except Exception as e:
            _logger.error(f"Error in /lms/api/auth/new_key: {str(e)}")
            return {"code": 500, "data": [], "message": f"Internal server error: {str(e)}"}

    @http.route('/lms/api/auth/revoke_keys', type='json', auth='bearer', methods=['POST'], csrf=False,
                cors='*')
    def revoke_keys(self, **kw):
        """Revoke ALL API keys for the current user."""
        try:
            Apikeys = request.env["res.users.apikeys"].sudo()
            keys = Apikeys.search([("user_id", "=", request.env.user.id)])
            n = len(keys)
            keys.unlink()
            return {"code": 200, "revoked": n}
        except Exception as e:
            _logger.error(f"Error in /lms/api/auth/revoke_keys: {str(e)}")
            return {"code": 500, "data": [], "message": f"Internal server error: {str(e)}"}

    @http.route('/lms/api/auth/me', type='json', auth='bearer', methods=['GET', 'POST'], csrf=False,
                cors='*')
    def whoami(self, **kw):
        """ Return info about the current user."""
        try:
            user = request.env.user.sudo()
            lounge = user.branch_id.lounge_id or None
            branch_ids = user.branch_ids or None
            vals = {
                "uid": user.id,
                "name": user.name,
                "permissions": {
                    #     "lms_group_user": user.has_group('lms_management.lms_group_user'),
                    #     "lms_group_supervisor": user.has_group('lms_management.lms_group_supervisor'),
                    #     "lms_group_finance": user.has_group('lms_management.lms_group_finance'),
                    #     "lms_group_manager": user.has_group('lms_management.lms_group_manager'),
                },
                "default_lounge": {"id": lounge.id,
                                   "name": lounge.name,
                                   "state": lounge.state_id.name or None,
                                   "airport": lounge.airport_id.name or None,
                                   "terminal": lounge.terminal_id.name or None,
                                   "logo": f"{get_base_url()}/web/content/{lounge.logo.id}" if lounge.logo and lounge.logo.public else "", } if lounge else None,
                "allowed_lounges": [{"id": branch.lounge_id.id,
                                     "name": branch.lounge_id.name,
                                     "state": branch.lounge_id.state_id.name or None,
                                     "airport": branch.lounge_id.airport_id.name or None,
                                     "terminal": branch.lounge_id.terminal_id.name or None,
                                     "logo": f"{get_base_url()}/web/content/{branch.lounge_id.logo.id}" if branch.lounge_id.logo and branch.lounge_id.logo.public else "", }
                                    for branch in branch_ids if
                                    branch.lounge_id] if user.branch_ids else None, }
            return {"code": 200, "data": vals}

        except Exception as e:
            _logger.error(f"Error in /lms/api/auth/me: {str(e)}")
            return {"code": 500, "data": [], "message": f"Internal server error: {str(e)}"}
