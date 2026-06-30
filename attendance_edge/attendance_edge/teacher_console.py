from __future__ import annotations

import json

import frappe
from frappe.utils import getdate, now_datetime

from attendance_edge.event_sync import get_sync_health
from attendance_edge.offline_auth import verify_teacher_pin
from attendance_edge.session_ops import get_local_session, insert_session_event, open_session
from attendance_edge.student_signature import _student_has_active_leave
from attendance_edge.totp_qr import get_qr_frame


VALID_MANUAL_STATES = {"Validated", "Rejected", "AttendanceCancelled"}


@frappe.whitelist(allow_guest=True)
def get_teacher_console(teacher_id: str, pin: str, session_date=None) -> dict:
    auth = _verify_teacher(teacher_id, pin)
    if not auth["ok"]:
        return auth

    target_date = getdate(session_date) if session_date else getdate(now_datetime())
    sessions = _teacher_sessions(teacher_id, target_date)
    return {
        "ok": True,
        "teacher": _teacher_payload(teacher_id),
        "session_date": str(target_date),
        "sessions": [_session_summary(row.name) for row in sessions],
        "sync": _safe_sync_health(),
    }


@frappe.whitelist(allow_guest=True)
def get_attendance_session(attendance_session_id: str, teacher_id: str, pin: str) -> dict:
    session = get_local_session(attendance_session_id)
    auth = _verify_teacher_for_session(session, teacher_id, pin)
    if not auth["ok"]:
        return auth
    return {"ok": True, "session": _session_detail(session), "sync": _safe_sync_health()}


@frappe.whitelist(allow_guest=True)
def open_attendance_session(attendance_session_id: str, teacher_id: str, pin: str) -> dict:
    session = get_local_session(attendance_session_id)
    auth = _verify_teacher_for_session(session, teacher_id, pin)
    if not auth["ok"]:
        return auth
    result = open_session(attendance_session_id, teacher_id, pin)
    session.reload()
    return {"ok": result.get("ok"), "status": result.get("status"), "result": result, "session": _session_detail(session)}


@frappe.whitelist(allow_guest=True)
def manual_mark_student(
    attendance_session_id: str,
    teacher_id: str,
    pin: str,
    student_id: str,
    attendance_state: str = "Validated",
    reason: str | None = None,
) -> dict:
    session = get_local_session(attendance_session_id)
    auth = _verify_teacher_for_session(session, teacher_id, pin)
    if not auth["ok"]:
        return auth
    if session.status != "Open":
        return {"ok": False, "status": "session_not_open"}

    state = attendance_state if attendance_state in VALID_MANUAL_STATES else "Validated"
    if not _student_on_roster(session.name, student_id):
        return {"ok": False, "status": "student_not_in_roster"}
    if state == "Validated" and _student_has_active_leave(session, student_id):
        return {"ok": False, "status": "student_on_leave"}
    if state == "Validated" and _student_has_validated_mark(session.name, student_id):
        return {"ok": True, "status": "already_marked", "session": _session_detail(session)}

    event = insert_session_event(
        session,
        "teacher_manual_mark",
        student_id=student_id,
        teacher_id=teacher_id,
        attendance_state=state,
        capture_source="Teacher",
        payload={"reason": reason or "", "manual": True},
    )
    return {"ok": True, "status": "marked", "event_id": event.event_id, "session": _session_detail(session)}


def _verify_teacher(teacher_id: str, pin: str) -> dict:
    pin_result = verify_teacher_pin(teacher_id, pin)
    if not pin_result.get("ok"):
        return {"ok": False, "status": "invalid_pin", "auth_status": pin_result.get("status")}
    return {"ok": True}


def _verify_teacher_for_session(session, teacher_id: str, pin: str) -> dict:
    auth = _verify_teacher(teacher_id, pin)
    if not auth["ok"]:
        return auth
    allowed = {value for value in (session.teacher_id, session.replacement_teacher_id) if value}
    if allowed and teacher_id not in allowed:
        return {"ok": False, "status": "forbidden_teacher"}
    return {"ok": True}


def _teacher_sessions(teacher_id: str, session_date):
    rows = frappe.get_all(
        "Local Session",
        filters={"session_date": session_date},
        or_filters=[{"teacher_id": teacher_id}, {"replacement_teacher_id": teacher_id}],
        fields=["name"],
        order_by="planned_start asc",
        ignore_permissions=True,
    )
    return rows


def _teacher_payload(teacher_id: str) -> dict:
    row = frappe.db.get_value(
        "Local User Teacher",
        teacher_id,
        ["teacher_id", "full_name", "user_id"],
        as_dict=True,
    )
    return dict(row or {"teacher_id": teacher_id})


def _session_summary(local_session_name: str) -> dict:
    session = frappe.get_doc("Local Session", local_session_name)
    summary = _attendance_summary(session)
    return {
        "name": session.name,
        "attendance_session_id": session.attendance_session_id,
        "module_code": session.module_code,
        "student_group": session.student_group,
        "room": session.room,
        "status": session.status,
        "session_date": str(session.session_date),
        "planned_start": str(session.planned_start),
        "planned_end": str(session.planned_end),
        "opened_at": str(session.opened_at) if session.opened_at else None,
        "closed_at": str(session.closed_at) if session.closed_at else None,
        "planning_sync_updated": bool(session.planning_sync_updated),
        "planning_conflict_detected": bool(session.planning_conflict_detected),
        "sync_status": session.sync_status,
        "summary": summary,
    }


def _session_detail(session) -> dict:
    payload = _session_summary(session.name)
    payload["roster"] = _roster_detail(session)
    payload["qr_frame"] = _safe_qr_frame(session)
    return payload


def _attendance_summary(session) -> dict:
    roster = _active_roster(session.name)
    statuses = _student_statuses(session, roster)
    counts = {"total": len(roster), "validated": 0, "pending": 0, "leave": 0, "rejected": 0, "not_signed": 0}
    for status in statuses.values():
        key = status.get("status")
        if key == "Validated":
            counts["validated"] += 1
        elif key == "Pending Validation":
            counts["pending"] += 1
        elif key == "Leave":
            counts["leave"] += 1
        elif key == "Rejected":
            counts["rejected"] += 1
        else:
            counts["not_signed"] += 1
    counts["remaining"] = max(0, counts["total"] - counts["validated"] - counts["pending"] - counts["leave"])
    return counts


def _roster_detail(session) -> list[dict]:
    roster = _active_roster(session.name)
    statuses = _student_statuses(session, roster)
    rows = []
    for row in roster:
        status = statuses.get(row.student_id) or {"status": "Not Signed"}
        rows.append(
            {
                "student_id": row.student_id,
                "student_name": row.student_name,
                "status": status["status"],
                "event_type": status.get("event_type"),
                "event_time": status.get("event_time"),
                "capture_source": status.get("capture_source"),
            }
        )
    return rows


def _active_roster(local_session_name: str):
    return frappe.get_all(
        "Local Session Roster",
        filters={"local_session": local_session_name, "roster_status": "Active"},
        fields=["student_id", "student_name"],
        order_by="student_name asc, student_id asc",
        ignore_permissions=True,
    )


def _student_statuses(session, roster) -> dict:
    statuses = {}
    for row in roster:
        if _student_has_active_leave(session, row.student_id):
            statuses[row.student_id] = {"status": "Leave"}

    events = frappe.get_all(
        "Local Attendance Event",
        filters={"local_session": session.name},
        fields=["student_id", "event_type", "attendance_state", "capture_source", "event_time", "payload_json"],
        order_by="event_time asc, creation asc",
        ignore_permissions=True,
    )
    for event in events:
        if not event.student_id:
            continue
        status = _status_from_event(event)
        if not status:
            continue
        if statuses.get(event.student_id, {}).get("status") == "Leave" and status != "Validated":
            continue
        statuses[event.student_id] = {
            "status": status,
            "event_type": event.event_type,
            "event_time": str(event.event_time) if event.event_time else None,
            "capture_source": event.capture_source,
        }
    return statuses


def _status_from_event(event) -> str | None:
    if event.event_type in {"student_signature_received", "student_signature_validated"}:
        return "Validated"
    if event.event_type == "student_provisional_checkin":
        return "Pending Validation"
    if event.event_type == "teacher_manual_mark":
        return event.attendance_state if event.attendance_state in VALID_MANUAL_STATES else None
    if event.event_type == "student_signature_rejected":
        try:
            reason = json.loads(event.payload_json or "{}").get("reason")
        except ValueError:
            reason = None
        return "Rejected" if reason and reason != "already_signed" else None
    return None


def _safe_qr_frame(session) -> dict | None:
    if session.status != "Open":
        return None
    try:
        return get_qr_frame(session.attendance_session_id)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "attendance_edge_teacher_console_qr_failed")
        return None


def _safe_sync_health() -> dict:
    try:
        return get_sync_health()
    except Exception:
        return {"ok": False, "status": "unavailable"}


def _student_on_roster(local_session_name: str, student_id: str) -> bool:
    return bool(
        frappe.db.exists(
            "Local Session Roster",
            {"local_session": local_session_name, "student_id": student_id, "roster_status": "Active"},
        )
    )


def _student_has_validated_mark(local_session_name: str, student_id: str) -> bool:
    return bool(
        frappe.get_all(
            "Local Attendance Event",
            filters={
                "local_session": local_session_name,
                "student_id": student_id,
                "event_type": ["in", ["student_signature_received", "student_signature_validated", "teacher_manual_mark"]],
                "attendance_state": "Validated",
            },
            limit_page_length=1,
            ignore_permissions=True,
        )
    )
