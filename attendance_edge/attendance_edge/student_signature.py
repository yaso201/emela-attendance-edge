from __future__ import annotations

import hashlib
import ipaddress
import json

import frappe
from frappe.utils import get_datetime, now_datetime

from attendance_edge.session_ops import get_local_session, insert_session_event
from attendance_edge.totp_qr import validate_qr_payload


DEFAULT_ALLOWED_CIDRS = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
MAX_FINGERPRINT_LENGTH = 140
FINGERPRINT_HASH_PREFIX = "sha256:"


@frappe.whitelist(allow_guest=True)
def provisional_checkin(attendance_session_id: str, student_id: str, fingerprint=None, remote_addr=None) -> dict:
    session = get_local_session(attendance_session_id)
    ok, reason = _check_student_signature_preconditions(
        session,
        student_id,
        remote_addr=remote_addr,
        allow_pending=True,
        require_open=False,
    )
    if not ok:
        _audit_rejection(session, student_id, reason, capture_source="Student Provisional")
        return {"ok": False, "status": reason}

    event = insert_session_event(
        session,
        "student_provisional_checkin",
        student_id=student_id,
        attendance_state="Pending Validation",
        capture_source="Student Provisional",
        payload={"fingerprint": _fingerprint_value(fingerprint), "provisional": True},
    )
    _record_fingerprint(student_id, event.event_id, fingerprint, remote_addr)
    return {"ok": True, "status": "pending_validation", "event_id": event.event_id}


@frappe.whitelist(allow_guest=True)
def submit_qr_signature(student_id: str, qr_payload, fingerprint=None, remote_addr=None) -> dict:
    payload = _parse_qr_payload(qr_payload)
    session = get_local_session(payload.get("session_id"))
    ok, reason = _check_student_signature_preconditions(
        session,
        student_id,
        remote_addr=remote_addr,
        allow_pending=False,
        require_open=True,
    )
    if not ok:
        _audit_rejection(session, student_id, reason, capture_source="Student QR")
        return {"ok": False, "status": reason}

    valid, reason = validate_qr_payload(session, payload)
    if not valid:
        _audit_rejection(session, student_id, reason or "invalid_qr", capture_source="Student QR")
        return {"ok": False, "status": reason or "invalid_qr"}

    event = insert_session_event(
        session,
        "student_signature_received",
        student_id=student_id,
        attendance_state="Validated",
        capture_source="Student QR",
        payload={"fingerprint": _fingerprint_value(fingerprint), "qr_issued_at": payload.get("issued_at")},
    )
    _record_fingerprint(student_id, event.event_id, fingerprint, remote_addr)
    return {"ok": True, "status": "validated", "event_id": event.event_id}


def _check_student_signature_preconditions(session, student_id, remote_addr=None, allow_pending=False, require_open=False):
    now = now_datetime()
    if session.status in {"Closed", "SessionCancelled", "Incident"}:
        return False, "Session Already Closed" if session.status == "Closed" else session.status
    if require_open and session.status != "Open":
        return False, "session_not_open"
    if not allow_pending and session.status != "Open":
        return False, "qr_required"
    if get_datetime(session.planned_end) <= now:
        return False, "Session Already Closed"
    if not is_request_from_local_network(remote_addr):
        return False, "outside_signature_network"
    if not _is_student_on_roster(session.name, student_id):
        return False, "student_not_in_roster"
    if _student_has_active_leave(session, student_id):
        return False, "student_on_leave"
    if _student_already_signed(session.name, student_id):
        return False, "already_signed"
    return True, None


def is_request_from_local_network(remote_addr=None) -> bool:
    address = remote_addr or _request_ip()
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    cidrs = frappe.conf.get("attendance_allowed_cidrs") or DEFAULT_ALLOWED_CIDRS
    if isinstance(cidrs, str):
        cidrs = [item.strip() for item in cidrs.split(",") if item.strip()]
    return any(ip in ipaddress.ip_network(cidr, strict=False) for cidr in cidrs)


def _is_student_on_roster(local_session, student_id):
    return bool(
        frappe.db.exists(
            "Local Session Roster",
            {"local_session": local_session, "student_id": student_id, "roster_status": "Active"},
        )
    )


def _student_has_active_leave(session, student_id):
    return bool(
        frappe.get_all(
            "Local Leave",
            filters={
                "student_id": student_id,
                "starts_at": ["<=", session.planned_end],
                "ends_at": [">=", session.planned_start],
            },
            limit_page_length=1,
            ignore_permissions=True,
        )
    )


def _student_already_signed(local_session, student_id):
    rows = frappe.get_all(
        "Local Attendance Event",
        filters={
            "local_session": local_session,
            "student_id": student_id,
            "event_type": ["in", ["student_provisional_checkin", "student_signature_received", "student_signature_validated"]],
            "attendance_state": ["in", ["Pending Validation", "Validated"]],
        },
        limit_page_length=1,
        ignore_permissions=True,
    )
    return bool(rows)


def _audit_rejection(session, student_id, reason, capture_source):
    try:
        insert_session_event(
            session,
            "student_signature_rejected",
            student_id=student_id,
            attendance_state="Rejected",
            capture_source=capture_source,
            payload={"reason": reason},
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "attendance_edge_student_signature_rejection_audit_failed")


def _record_fingerprint(student_id, event_id, fingerprint, remote_addr=None):
    if not isinstance(fingerprint, dict):
        return None
    value = _fingerprint_value(fingerprint)
    if not value:
        return None
    return frappe.get_doc(
        {
            "doctype": "Local Device Fingerprint",
            "student_id": student_id,
            "event_id": event_id,
            "fingerprint": value,
            "user_agent": fingerprint.get("user_agent"),
            "local_ip": remote_addr or fingerprint.get("local_ip") or _request_ip(),
            "screen_resolution": fingerprint.get("screen_resolution"),
            "timezone": fingerprint.get("timezone"),
            "captured_at": now_datetime(),
        }
    ).insert(ignore_permissions=True)


def _fingerprint_value(fingerprint):
    if isinstance(fingerprint, dict):
        value = fingerprint.get("fingerprint")
    elif isinstance(fingerprint, str):
        value = fingerprint
    else:
        return None
    if not value:
        return None
    value = str(value).strip()
    if len(value) <= MAX_FINGERPRINT_LENGTH:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{FINGERPRINT_HASH_PREFIX}{digest}"


def _parse_qr_payload(qr_payload):
    if isinstance(qr_payload, str):
        try:
            return json.loads(qr_payload)
        except ValueError:
            return {}
    return qr_payload if isinstance(qr_payload, dict) else {}


def _request_ip():
    request = getattr(frappe.local, "request", None)
    if request:
        return request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip() or request.remote_addr
    return getattr(frappe.local, "request_ip", None)
