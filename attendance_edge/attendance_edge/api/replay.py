from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from attendance_edge.event_sync import push_pending_events_to_central, replay_event_for_sync


CLOSURE_EVENTS = {
    "session_closed",
    "session_auto_closed",
    "session_auto_closed_post_restart",
}
ATTENDANCE_REPLAY_EVENTS = {
    "student_signature_received",
    "student_signature_validated",
    "teacher_manual_mark",
    "paper_mode_used",
    "leave_applied",
}


@frappe.whitelist()
def replay_local_events(
    request_id: str | None = None,
    anomaly_type: str | None = None,
    attendance_session_id: str | None = None,
    session_id: str | None = None,
    event_id: str | None = None,
    student_id: str | None = None,
    sync_now: int = 1,
) -> dict:
    _require_system_manager()
    events = _find_events(
        anomaly_type=anomaly_type,
        attendance_session_id=attendance_session_id,
        session_id=session_id,
        event_id=event_id,
        student_id=student_id,
    )
    if not events:
        return {
            "status": "no_events",
            "request_id": request_id,
            "queued": 0,
            "events": [],
        }

    queue_names = [replay_event_for_sync(row.name) for row in events]
    sync_result = None
    status = "queued"
    if cint(sync_now):
        sync_result = push_pending_events_to_central(limit=max(len(queue_names), 1))
        if cint(sync_result.get("acknowledged")):
            status = "synced"

    return {
        "status": status,
        "request_id": request_id,
        "queued": len(queue_names),
        "queues": queue_names,
        "events": [row.event_id for row in events],
        "sync_result": sync_result,
    }


def _find_events(
    *,
    anomaly_type: str | None,
    attendance_session_id: str | None,
    session_id: str | None,
    event_id: str | None,
    student_id: str | None,
) -> list:
    session_name = _resolve_session(attendance_session_id, session_id)
    filters = {}
    if event_id:
        filters["event_id"] = event_id
    if session_name:
        filters["local_session"] = session_name
    elif session_id:
        filters["session_id"] = session_id
    elif not event_id:
        frappe.throw(_("Session locale ou event_id requis pour le rejeu local."))

    if student_id:
        filters["student_id"] = student_id

    event_types = _event_types_for_anomaly(anomaly_type, bool(event_id))
    if event_types:
        filters["event_type"] = ["in", sorted(event_types)]

    return frappe.get_all(
        "Local Attendance Event",
        filters=filters,
        fields=["name", "event_id", "event_type", "student_id"],
        order_by="event_time asc, creation asc",
        limit_page_length=100,
        ignore_permissions=True,
    )


def _resolve_session(attendance_session_id: str | None, session_id: str | None) -> str | None:
    if attendance_session_id:
        name = (
            frappe.db.exists("Local Session", attendance_session_id)
            or frappe.db.exists("Local Session", {"attendance_session_id": attendance_session_id})
        )
        if name:
            return name
    if session_id:
        return frappe.db.exists("Local Session", {"session_id": session_id})
    return None


def _event_types_for_anomaly(anomaly_type: str | None, has_event_id: bool) -> set[str] | None:
    if has_event_id:
        return None
    if anomaly_type == "missing_closure_event":
        return CLOSURE_EVENTS
    if anomaly_type in {
        "session_missing_consolidation",
        "missing_student_attendance",
        "status_event_mismatch",
    }:
        return ATTENDANCE_REPLAY_EVENTS | CLOSURE_EVENTS
    return None


def _require_system_manager() -> None:
    if "System Manager" not in frappe.get_roles(frappe.session.user):
        frappe.throw(_("Acces non autorise pour le rejeu local attendance."), frappe.PermissionError)
