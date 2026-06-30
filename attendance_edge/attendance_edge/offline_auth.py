from __future__ import annotations

import time

import frappe
from frappe.utils import cint, now_datetime
from frappe.utils.password import get_decrypted_password, passlibctx


MAX_FAILURES = 3
LOCK_SECONDS = 300
FAILURE_BUCKET = "attendance_edge_auth_failures"
LOCK_BUCKET = "attendance_edge_auth_locks"


@frappe.whitelist(allow_guest=True)
def authenticate(user_id: str, password: str, actor_type: str | None = None):
    return authenticate_offline(user_id=user_id, password=password, actor_type=actor_type)


@frappe.whitelist(allow_guest=True)
def verify_pin(teacher_id: str, pin: str):
    return verify_teacher_pin(teacher_id=teacher_id, pin=pin)


def authenticate_offline(user_id: str, password: str, actor_type: str | None = None) -> dict:
    identifier = (user_id or "").strip()
    key = f"password:{actor_type or 'any'}:{identifier}"
    if _is_locked(key):
        return {"ok": False, "status": "locked"}

    local_user = _find_local_user(identifier, actor_type)
    if not local_user:
        return _fail(key, "invalid_credentials")

    doctype, name = local_user
    if frappe.db.get_value(doctype, name, "status") != "Active":
        return _fail(key, "disabled")

    password_hash = get_decrypted_password(doctype, name, "password_hash", raise_exception=False)
    if password_hash and passlibctx.verify(password or "", password_hash):
        _clear_failures(key)
        return {"ok": True, "status": "authenticated", "doctype": doctype, "name": name}

    return _fail(key, "invalid_credentials")


def verify_teacher_pin(teacher_id: str, pin: str) -> dict:
    identifier = (teacher_id or "").strip()
    key = f"pin:{identifier}"
    if _is_locked(key):
        return {"ok": False, "status": "locked"}
    if len(pin or "") != 6 or not str(pin).isdigit():
        return _fail(key, "invalid_pin_format")

    if not frappe.db.exists("Local User Teacher", identifier):
        return _fail(key, "teacher_not_found")
    if frappe.db.get_value("Local User Teacher", identifier, "status") != "Active":
        return _fail(key, "disabled")

    pin_hash = get_decrypted_password("Local User Teacher", identifier, "pin_hash", raise_exception=False)
    if pin_hash and passlibctx.verify(pin, pin_hash):
        _clear_failures(key)
        return {"ok": True, "status": "pin_verified", "teacher": identifier}

    _record_pin_failure(identifier)
    return _fail(key, "invalid_pin")


def clear_auth_rate_limit(identifier: str, actor_type: str | None = None):
    for key in (
        f"password:{actor_type or 'any'}:{identifier}",
        f"pin:{identifier}",
    ):
        _clear_failures(key)


def _find_local_user(identifier, actor_type=None):
    candidates = []
    if actor_type in (None, "student"):
        candidates.extend([
            ("Local User Student", {"name": identifier}),
            ("Local User Student", {"user_id": identifier}),
        ])
    if actor_type in (None, "teacher"):
        candidates.extend([
            ("Local User Teacher", {"name": identifier}),
            ("Local User Teacher", {"user_id": identifier}),
        ])

    for doctype, filters in candidates:
        name = frappe.db.exists(doctype, filters)
        if name:
            return doctype, name
    return None


def _fail(key, reason):
    attempts = _record_failure(key)
    return {
        "ok": False,
        "status": "locked" if attempts >= MAX_FAILURES else reason,
        "reason": reason,
        "attempts": attempts,
    }


def _record_failure(key):
    cache = frappe.cache()
    attempts = cint(cache.hget(FAILURE_BUCKET, key) or 0) + 1
    cache.hset(FAILURE_BUCKET, key, attempts)
    if attempts >= MAX_FAILURES:
        cache.hset(LOCK_BUCKET, key, int(time.time()) + LOCK_SECONDS)
    return attempts


def _record_pin_failure(teacher_id):
    try:
        frappe.get_doc(
            {
                "doctype": "Local Attendance Event",
                "event_id": frappe.generate_hash(length=20),
                "session_id": "AUTH",
                "teacher_id": teacher_id,
                "event_type": "incident_detected",
                "event_time": now_datetime(),
                "attendance_state": "N/A",
                "capture_source": "System",
                "payload_json": '{"type":"teacher_pin_attempt_failed"}',
            }
        ).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "attendance_edge teacher_pin_attempt_failed audit")


def _is_locked(key):
    locked_until = cint(frappe.cache().hget(LOCK_BUCKET, key) or 0)
    return bool(locked_until and locked_until > int(time.time()))


def _clear_failures(key):
    cache = frappe.cache()
    cache.hdel(FAILURE_BUCKET, key)
    cache.hdel(LOCK_BUCKET, key)
