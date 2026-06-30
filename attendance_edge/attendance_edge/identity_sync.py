from __future__ import annotations

import json
from urllib.parse import urljoin

import frappe
import requests
from frappe.utils import now_datetime


STUDENT_EXPORT_ROUTE = "/api/method/portal_app.api.attendance_identity_export.export_students"
TEACHER_EXPORT_ROUTE = "/api/method/portal_app.api.attendance_identity_export.export_teachers"


def sync_identity_payload(payload: dict, identity_type: str) -> dict:
    rows = _extract_rows(payload)
    counters = {"created": 0, "updated": 0, "skipped": 0}

    for row in rows:
        if identity_type == "students":
            status = _upsert_student(row)
        elif identity_type == "teachers":
            status = _upsert_teacher(row)
        else:
            frappe.throw(f"Unsupported identity type: {identity_type}")
        counters[status] += 1

    return {"status": "synced", "identity_type": identity_type, **counters}


def sync_identities_from_central(updated_after=None, page_size=200) -> dict:
    config = _get_central_config()
    result = {"students": _sync_kind("students", config, updated_after, page_size)}
    result["teachers"] = _sync_kind("teachers", config, updated_after, page_size)
    return result


def _sync_kind(identity_type, config, updated_after, page_size):
    page = 1
    total = {"created": 0, "updated": 0, "skipped": 0}
    while True:
        payload = _fetch_identity_page(identity_type, config, page, page_size, updated_after)
        step = sync_identity_payload(payload, identity_type)
        for key in total:
            total[key] += step[key]
        pagination = payload.get("pagination") or {}
        if not pagination.get("has_next"):
            break
        page += 1
    return total


def _fetch_identity_page(identity_type, config, page, page_size, updated_after=None):
    route = STUDENT_EXPORT_ROUTE if identity_type == "students" else TEACHER_EXPORT_ROUTE
    url = urljoin(config["base_url"].rstrip("/") + "/", route.lstrip("/"))
    params = {"page": page, "page_size": page_size}
    if updated_after:
        params["updated_after"] = updated_after

    response = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Token {config['api_token']}"},
        timeout=config["timeout"],
    )
    response.raise_for_status()
    data = response.json()
    return data.get("message", data) if isinstance(data, dict) else data


def _get_central_config():
    base_url = frappe.conf.get("attendance_central_base_url")
    api_token = frappe.conf.get("attendance_central_api_token")
    if not base_url or not api_token:
        frappe.throw("Configuration attendance_central_base_url/api_token absente.")
    return {
        "base_url": base_url,
        "api_token": api_token,
        "timeout": int(frappe.conf.get("attendance_central_timeout") or 30),
    }


def _extract_rows(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data.get("data"), list):
            return data["data"]
    return []


def _upsert_student(row):
    student_id = row.get("student_id")
    user_id = row.get("user_id")
    password_hash = row.get("password_hash")
    if not student_id or not user_id:
        return "skipped"

    existing = frappe.db.exists("Local User Student", student_id)
    if not existing and not password_hash:
        return "skipped"

    doc = frappe.get_doc("Local User Student", student_id) if existing else frappe.new_doc("Local User Student")
    doc.student_id = student_id
    doc.user_id = user_id
    doc.first_name = row.get("first_name")
    doc.last_name = row.get("last_name")
    doc.full_name = row.get("full_name")
    if password_hash:
        doc.password_hash = password_hash
    doc.groups_json = json.dumps(row.get("groups") or [], ensure_ascii=False, sort_keys=True)
    doc.status = _coerce_status(row.get("status"))
    doc.source_version = row.get("source_version")
    doc.last_synced_at = now_datetime()
    doc.save(ignore_permissions=True) if existing else doc.insert(ignore_permissions=True)
    return "updated" if existing else "created"


def _upsert_teacher(row):
    teacher_id = row.get("teacher_id")
    user_id = row.get("user_id")
    password_hash = row.get("password_hash")
    if not teacher_id or not user_id:
        return "skipped"

    existing = frappe.db.exists("Local User Teacher", teacher_id)
    if not existing and not password_hash:
        return "skipped"

    doc = frappe.get_doc("Local User Teacher", teacher_id) if existing else frappe.new_doc("Local User Teacher")
    doc.teacher_id = teacher_id
    doc.user_id = user_id
    doc.first_name = row.get("first_name")
    doc.last_name = row.get("last_name")
    doc.full_name = row.get("full_name")
    if password_hash:
        doc.password_hash = password_hash
    if row.get("pin_hash"):
        doc.pin_hash = row.get("pin_hash")
    doc.status = _coerce_status(row.get("status"))
    doc.permissions_json = json.dumps(row.get("permissions") or {}, ensure_ascii=False, sort_keys=True)
    doc.authorized_sessions_json = json.dumps(row.get("authorized_sessions") or [], ensure_ascii=False, sort_keys=True)
    doc.source_version = row.get("source_version")
    doc.last_synced_at = now_datetime()
    doc.save(ignore_permissions=True) if existing else doc.insert(ignore_permissions=True)
    return "updated" if existing else "created"


def _coerce_status(status):
    return status if status in {"Active", "Disabled", "Suspended"} else "Disabled"
