from __future__ import annotations

import json

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from attendance_edge.event_sync import queue_event_for_sync
from attendance_edge.offline_auth import verify_teacher_pin
from attendance_edge.totp_qr import generate_session_secret


@frappe.whitelist()
def open_session(attendance_session_id: str, teacher_id: str, pin: str) -> dict:
    session = get_local_session(attendance_session_id)
    if session.status == "Open":
        return {"ok": True, "status": "already_open", "session": session.name}
    if session.status in {"Closed", "SessionCancelled", "Incident"}:
        return {"ok": False, "status": "not_openable", "reason": session.status}
    if session.teacher_id and teacher_id not in {session.teacher_id, session.replacement_teacher_id}:
        return {"ok": False, "status": "forbidden_teacher"}
    if get_datetime(session.planned_end) <= now_datetime():
        return {"ok": False, "status": "session_already_ended"}

    pin_result = verify_teacher_pin(teacher_id, pin)
    if not pin_result.get("ok"):
        return {"ok": False, "status": "invalid_pin", "auth_status": pin_result.get("status")}

    now = now_datetime()
    session.status = "Open"
    session.opened_at = now
    session.closed_at = None
    session.secret_session = generate_session_secret()
    session.secret_generated_at = now
    session.secret_purge_after = None
    session.save(ignore_permissions=True)

    _insert_event(
        session,
        "session_opened",
        teacher_id=teacher_id,
        attendance_state="N/A",
        capture_source="Teacher",
        payload={"session_version": session.session_version},
    )
    converted = convert_provisional_checkins(session)
    return {"ok": True, "status": "opened", "session": session.name, "converted_provisional": converted}


def close_due_sessions(reference_time=None, post_restart=False) -> dict:
    now = get_datetime(reference_time) if reference_time else now_datetime()
    sessions = frappe.get_all(
        "Local Session",
        filters={"status": "Open", "planned_end": ["<=", now]},
        fields=["name"],
        ignore_permissions=True,
    )
    closed = []
    for row in sessions:
        session = frappe.get_doc("Local Session", row.name)
        close_session(session, reference_time=now, post_restart=post_restart)
        closed.append(session.name)
    return {"status": "closed", "count": len(closed), "sessions": closed}


def close_session(session, reference_time=None, post_restart=False):
    now = get_datetime(reference_time) if reference_time else now_datetime()
    session.status = "Closed"
    session.closed_at = now
    session.secret_purge_after = add_to_date(now, hours=1, as_datetime=True)
    session.save(ignore_permissions=True)
    _insert_event(
        session,
        "session_auto_closed_post_restart" if post_restart else "session_auto_closed",
        attendance_state="N/A",
        capture_source="System",
        event_time=now,
        payload={"post_restart": bool(post_restart), "session_version": session.session_version},
    )
    return session


def purge_expired_session_secrets(reference_time=None) -> dict:
    now = get_datetime(reference_time) if reference_time else now_datetime()
    sessions = frappe.get_all(
        "Local Session",
        filters={"status": "Closed", "secret_purge_after": ["<=", now]},
        fields=["name"],
        ignore_permissions=True,
    )
    purged = []
    for row in sessions:
        session = frappe.get_doc("Local Session", row.name)
        session.secret_session = None
        session.secret_generated_at = None
        session.secret_purge_after = None
        session.save(ignore_permissions=True)
        purged.append(session.name)
    return {"status": "purged", "count": len(purged), "sessions": purged}


def convert_provisional_checkins(session) -> int:
    rows = frappe.get_all(
        "Local Attendance Event",
        filters={
            "local_session": session.name,
            "event_type": "student_provisional_checkin",
            "attendance_state": "Pending Validation",
        },
        fields=["name", "event_id", "student_id", "event_time"],
        ignore_permissions=True,
    )
    converted = 0
    for row in rows:
        if _validation_exists(row.event_id):
            continue
        _insert_event(
            session,
            "student_signature_validated",
            student_id=row.student_id,
            attendance_state="Validated",
            capture_source="Student Provisional",
            event_time=now_datetime(),
            payload={"source_event_id": row.event_id, "validated_on_open": True},
        )
        converted += 1
    return converted


def get_local_session(identifier: str):
    name = (
        frappe.db.exists("Local Session", identifier)
        or frappe.db.exists("Local Session", {"attendance_session_id": identifier})
        or frappe.db.exists("Local Session", {"session_id": identifier})
    )
    if not name:
        frappe.throw("Session locale introuvable.")
    return frappe.get_doc("Local Session", name)


def insert_session_event(session, event_type: str, **kwargs):
    return _insert_event(session, event_type, **kwargs)


def _insert_event(
    session,
    event_type,
    student_id=None,
    teacher_id=None,
    attendance_state="N/A",
    capture_source="N/A",
    event_time=None,
    payload=None,
):
    event = frappe.get_doc(
        {
            "doctype": "Local Attendance Event",
            "event_id": _event_id(event_type),
            "local_session": session.name,
            "session_id": session.session_id,
            "student_id": student_id,
            "teacher_id": teacher_id,
            "event_type": event_type,
            "event_time": event_time or now_datetime(),
            "attendance_state": attendance_state,
            "capture_source": capture_source,
            "payload_json": json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
        }
    ).insert(ignore_permissions=True)
    queue_event_for_sync(event)
    return event


def _validation_exists(source_event_id):
    return bool(
        frappe.get_all(
            "Local Attendance Event",
            filters={"event_type": "student_signature_validated", "payload_json": ["like", f"%{source_event_id}%"]},
            limit_page_length=1,
            ignore_permissions=True,
        )
    )


def _event_id(prefix):
    return f"{prefix}-{frappe.generate_hash(length=16)}"
