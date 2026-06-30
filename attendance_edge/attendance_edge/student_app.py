from __future__ import annotations

import frappe
from frappe.utils import get_datetime, now_datetime

from attendance_edge.student_signature import _student_has_active_leave


@frappe.whitelist(allow_guest=True)
def get_student_context(student_id: str) -> dict:
    student = _student_payload(student_id)
    if not student:
        return {"ok": False, "status": "student_not_found"}
    if student.get("status") != "Active":
        return {"ok": False, "status": "student_disabled"}

    return {
        "ok": True,
        "student": student,
        "sessions": [_session_payload(session, student_id) for session in _student_sessions(student_id)],
    }


def _student_payload(student_id: str) -> dict | None:
    row = frappe.db.get_value(
        "Local User Student",
        student_id,
        ["student_id", "full_name", "user_id", "status"],
        as_dict=True,
    )
    return dict(row) if row else None


def _student_roster_rows(student_id: str):
    return frappe.get_all(
        "Local Session Roster",
        filters={"student_id": student_id, "roster_status": "Active"},
        fields=["local_session"],
        order_by="creation desc",
        ignore_permissions=True,
    )


def _student_sessions(student_id: str):
    sessions = []
    now = now_datetime()
    for row in _student_roster_rows(student_id):
        session = frappe.get_doc("Local Session", row.local_session)
        if session.status == "Open" or get_datetime(session.planned_end) > now:
            sessions.append(session)
    return sorted(sessions, key=lambda session: get_datetime(session.planned_start))


def _session_payload(session, student_id: str) -> dict:
    status = _student_session_status(session, student_id)
    return {
        "attendance_session_id": session.attendance_session_id,
        "module_code": session.module_code,
        "student_group": session.student_group,
        "room": session.room,
        "status": session.status,
        "student_status": status,
        "session_date": str(session.session_date),
        "planned_start": str(session.planned_start),
        "planned_end": str(session.planned_end),
        "can_provisional_checkin": _can_provisional_checkin(session, status),
    }


def _student_session_status(session, student_id: str) -> str:
    if _student_has_active_leave(session, student_id):
        return "Leave"
    rows = frappe.get_all(
        "Local Attendance Event",
        filters={
            "local_session": session.name,
            "student_id": student_id,
            "event_type": ["in", ["student_signature_received", "student_signature_validated", "student_provisional_checkin", "teacher_manual_mark"]],
        },
        fields=["event_type", "attendance_state"],
        order_by="event_time desc, creation desc",
        limit_page_length=1,
        ignore_permissions=True,
    )
    if not rows:
        return "Not Signed"
    row = rows[0]
    if row.event_type == "student_provisional_checkin":
        return "Pending Validation"
    if row.attendance_state in {"Validated", "Rejected", "AttendanceCancelled"}:
        return row.attendance_state
    return "Not Signed"


def _can_provisional_checkin(session, student_status: str) -> bool:
    if student_status not in {"Not Signed", "Rejected"}:
        return False
    if session.status in {"Closed", "SessionCancelled", "Incident"}:
        return False
    return get_datetime(session.planned_end) > now_datetime()
