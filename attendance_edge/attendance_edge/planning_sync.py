from __future__ import annotations

import json
from urllib.parse import urljoin

import frappe
import requests
from frappe.utils import cint, now_datetime

from attendance_edge.identity_sync import _get_central_config


PLANNING_EXPORT_ROUTE = "/api/method/portal_app.api.attendance_planning_export.export_planning"


def sync_planning_payload(payload: dict) -> dict:
    rows = _extract_rows(payload)
    counters = {
        "sessions_created": 0,
        "sessions_updated": 0,
        "sessions_skipped": 0,
        "roster_upserts": 0,
        "roster_removed": 0,
        "leaves_upserted": 0,
    }

    for row in rows:
        session, status = _upsert_session(row)
        counters[f"sessions_{status}"] += 1
        if not session:
            continue
        roster_stats = _sync_roster(session.name, row.get("roster") or [])
        counters["roster_upserts"] += roster_stats["upserts"]
        counters["roster_removed"] += roster_stats["removed"]
        counters["leaves_upserted"] += _sync_leaves(row.get("leaves") or [])

    return {"status": "synced", **counters}


def sync_planning_from_central(start_date=None, business_days=5, page_size=200) -> dict:
    config = _get_central_config()
    page = 1
    total = {
        "sessions_created": 0,
        "sessions_updated": 0,
        "sessions_skipped": 0,
        "roster_upserts": 0,
        "roster_removed": 0,
        "leaves_upserted": 0,
    }
    while True:
        payload = _fetch_planning_page(config, page, page_size, start_date, business_days)
        step = sync_planning_payload(payload)
        for key in total:
            total[key] += step[key]
        pagination = payload.get("pagination") or {}
        if not pagination.get("has_next"):
            break
        page += 1
    return {"status": "synced", **total}


def _fetch_planning_page(config, page, page_size, start_date=None, business_days=5):
    url = urljoin(config["base_url"].rstrip("/") + "/", PLANNING_EXPORT_ROUTE.lstrip("/"))
    params = {"page": page, "page_size": page_size, "business_days": business_days}
    if start_date:
        params["start_date"] = start_date
    response = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Token {config['api_token']}"},
        timeout=config["timeout"],
    )
    response.raise_for_status()
    data = response.json()
    return data.get("message", data) if isinstance(data, dict) else data


def _extract_rows(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return []


def _upsert_session(row):
    attendance_session_id = row.get("attendance_session_id")
    if not attendance_session_id or not row.get("session_id"):
        return None, "skipped"

    existing_name = frappe.db.exists("Local Session", {"attendance_session_id": attendance_session_id})
    doc = frappe.get_doc("Local Session", existing_name) if existing_name else frappe.new_doc("Local Session")
    incoming_status = _coerce_session_status(row.get("status"))
    if existing_name and doc.status == "Closed":
        if _has_structural_change(doc, row):
            doc.planning_conflict_detected = 1
            doc.save(ignore_permissions=True)
            return doc, "updated"
        return doc, "skipped"

    if existing_name and doc.status == "Open" and _has_structural_change(doc, row):
        doc.planning_sync_updated = 1
    if existing_name and doc.status == "Open" and incoming_status == "SessionCancelled":
        doc.planning_conflict_detected = 1

    doc.attendance_session_id = attendance_session_id
    doc.session_id = row.get("session_id")
    doc.session_version = cint(row.get("session_version")) or 1
    doc.module_code = row.get("module_code")
    doc.student_group = row.get("student_group")
    doc.teacher_id = row.get("teacher_id")
    doc.replacement_teacher_id = row.get("replacement_teacher_id")
    doc.department = row.get("department")
    doc.session_date = row.get("session_date")
    doc.planned_start = row.get("planned_start")
    doc.planned_end = row.get("planned_end")
    doc.room = row.get("room")
    doc.status = doc.status if existing_name and doc.status == "Open" else incoming_status
    doc.paper_mode_used = cint(row.get("paper_mode_used"))
    if cint(row.get("planning_conflict_detected")):
        doc.planning_conflict_detected = 1
    doc.sync_status = "Synced"
    doc.save(ignore_permissions=True) if existing_name else doc.insert(ignore_permissions=True)
    return doc, "updated" if existing_name else "created"


def _has_structural_change(doc, row):
    comparisons = {
        "session_version": cint(row.get("session_version")) or 1,
        "planned_start": str(row.get("planned_start") or ""),
        "planned_end": str(row.get("planned_end") or ""),
        "room": row.get("room") or "",
        "teacher_id": row.get("teacher_id") or "",
        "replacement_teacher_id": row.get("replacement_teacher_id") or "",
    }
    return (
        cint(doc.session_version) != comparisons["session_version"]
        or str(doc.planned_start or "") != comparisons["planned_start"]
        or str(doc.planned_end or "") != comparisons["planned_end"]
        or (doc.room or "") != comparisons["room"]
        or (doc.teacher_id or "") != comparisons["teacher_id"]
        or (doc.replacement_teacher_id or "") != comparisons["replacement_teacher_id"]
    )


def _sync_roster(local_session, roster_rows):
    incoming = {
        row.get("student_id"): row
        for row in roster_rows
        if isinstance(row, dict) and row.get("student_id")
    }
    upserts = 0
    removed = 0
    for student_id, row in incoming.items():
        existing = frappe.db.exists(
            "Local Session Roster",
            {"local_session": local_session, "student_id": student_id},
        )
        doc = frappe.get_doc("Local Session Roster", existing) if existing else frappe.new_doc("Local Session Roster")
        doc.local_session = local_session
        doc.student = frappe.db.exists("Local User Student", student_id) or None
        doc.student_id = student_id
        doc.student_name = row.get("student_name")
        doc.roster_status = row.get("roster_status") if row.get("roster_status") in {"Active", "Removed"} else "Active"
        doc.save(ignore_permissions=True) if existing else doc.insert(ignore_permissions=True)
        upserts += 1

    existing_rows = frappe.get_all(
        "Local Session Roster",
        filters={"local_session": local_session},
        fields=["name", "student_id", "roster_status"],
        ignore_permissions=True,
    )
    for existing in existing_rows:
        if existing.student_id not in incoming and existing.roster_status != "Removed":
            frappe.db.set_value("Local Session Roster", existing.name, "roster_status", "Removed")
            removed += 1
    return {"upserts": upserts, "removed": removed}


def _sync_leaves(leave_rows):
    count = 0
    for row in leave_rows:
        if not isinstance(row, dict) or not row.get("leave_id") or not row.get("student_id"):
            continue
        existing = frappe.db.exists("Local Leave", {"leave_id": row.get("leave_id")})
        doc = frappe.get_doc("Local Leave", existing) if existing else frappe.new_doc("Local Leave")
        doc.leave_id = row.get("leave_id")
        doc.student_id = row.get("student_id")
        doc.starts_at = row.get("starts_at")
        doc.ends_at = row.get("ends_at")
        doc.covered_sessions_json = json.dumps(row.get("covered_sessions") or [], ensure_ascii=False, sort_keys=True)
        doc.approved_by = row.get("approved_by")
        doc.approved_at = row.get("approved_at")
        doc.source_version = row.get("source_version")
        doc.last_synced_at = now_datetime()
        doc.save(ignore_permissions=True) if existing else doc.insert(ignore_permissions=True)
        count += 1
    return count


def _coerce_session_status(status):
    return status if status in {"Pending", "Open", "Closed", "SessionCancelled", "Incident"} else "Pending"
