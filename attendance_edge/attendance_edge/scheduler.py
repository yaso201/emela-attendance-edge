from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from attendance_edge.event_sync import ensure_sync_health, push_pending_events_to_central
from attendance_edge.heartbeat import send_heartbeat_to_central
from attendance_edge.planning_sync import sync_planning_from_central
from attendance_edge.session_ops import close_due_sessions, purge_expired_session_secrets


def run_opportunistic_sync() -> dict:
    """Fast local scheduler: push events and optionally poll urgent planning updates."""
    result = {
        "events": _run_step("event_sync", push_pending_events_to_central),
        "health": _run_step("sync_health", ensure_sync_health),
        "heartbeat": _run_step("heartbeat", send_heartbeat_to_central),
    }
    if int(frappe.conf.get("attendance_enable_planning_polling", 1)):
        result["planning"] = _run_step(
            "planning_poll",
            sync_planning_from_central,
            business_days=int(frappe.conf.get("attendance_planning_business_days") or 5),
        )
    return result


def run_closure_tick() -> dict:
    return {
        "closures": _run_step("close_due_sessions", close_due_sessions),
        "secret_purge": _run_step("purge_expired_session_secrets", purge_expired_session_secrets),
    }


def run_daily_planning_preload() -> dict:
    return _run_step(
        "daily_planning_preload",
        sync_planning_from_central,
        business_days=int(frappe.conf.get("attendance_planning_business_days") or 5),
    )


def monitor_sync_queue() -> dict:
    return _run_step(
        "sync_queue_monitor",
        ensure_sync_health,
        max_unsynced_hours=int(frappe.conf.get("attendance_max_unsynced_hours") or 4),
    )


def _run_step(step, fn, **kwargs):
    try:
        return fn(**kwargs)
    except Exception as exc:
        _record_scheduler_incident(step, exc)
        return {"status": "failed", "step": step, "error": str(exc)}


def _record_scheduler_incident(step, exc):
    description = f"Attendance scheduler step failed: {step}"
    existing = frappe.db.exists(
        "Local Incident",
        {"incident_type": "Sync", "status": "Open", "description": description},
    )
    if existing:
        return existing
    return frappe.get_doc(
        {
            "doctype": "Local Incident",
            "incident_type": "Sync",
            "severity": "High",
            "detected_at": now_datetime(),
            "description": description,
        }
    ).insert(ignore_permissions=True).name
