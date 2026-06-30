from __future__ import annotations

import json
from urllib.parse import urljoin

import frappe
import requests
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from attendance_edge.identity_sync import _get_central_config


EVENT_INGEST_ROUTE = "/api/method/portal_app.api.attendance_event_ingest.ingest_events"
BACKOFF_SECONDS = [1, 2, 4, 8, 16, 60, 300, 1800, 3600]


def queue_event_for_sync(local_event) -> str:
    event = frappe.get_doc("Local Attendance Event", local_event) if isinstance(local_event, str) else local_event
    existing = frappe.db.exists("Local Sync Queue", {"event_id": event.event_id})
    if existing:
        return existing
    queue = frappe.get_doc(
        {
            "doctype": "Local Sync Queue",
            "event_id": event.event_id,
            "local_event": event.name,
            "status": "Pending",
            "attempt_count": 0,
            "payload_json": json.dumps(_serialize_event(event), ensure_ascii=False, sort_keys=True),
        }
    ).insert(ignore_permissions=True)
    return queue.name


def replay_event_for_sync(local_event) -> str:
    event = frappe.get_doc("Local Attendance Event", local_event) if isinstance(local_event, str) else local_event
    payload_json = json.dumps(_serialize_event(event), ensure_ascii=False, sort_keys=True)
    existing = frappe.db.exists("Local Sync Queue", {"event_id": event.event_id})
    if existing:
        queue = frappe.get_doc("Local Sync Queue", existing)
        queue.status = "Pending"
        queue.attempt_count = 0
        queue.next_retry_at = None
        queue.last_error = None
        queue.payload_json = payload_json
        queue.save(ignore_permissions=True)
        return queue.name
    return queue_event_for_sync(event)


def push_pending_events_to_central(limit=100) -> dict:
    queues = _get_due_queue(limit)
    if not queues:
        return {"status": "idle", "sent": 0, "acknowledged": 0, "failed": 0}

    docs = [frappe.get_doc("Local Sync Queue", row.name) for row in queues]
    events = [_queue_payload(doc) for doc in docs]
    for doc in docs:
        doc.status = "Sent"
        doc.attempt_count = cint(doc.attempt_count) + 1
        doc.last_attempt_at = now_datetime()
        doc.save(ignore_permissions=True)

    try:
        response = _post_event_batch(events, _get_central_config())
        acknowledged = _apply_ack(response, docs)
        return {"status": "sent", "sent": len(docs), "acknowledged": acknowledged, "failed": len(docs) - acknowledged}
    except Exception as exc:
        for doc in docs:
            _mark_failed(doc, str(exc))
        return {"status": "failed", "sent": len(docs), "acknowledged": 0, "failed": len(docs)}


def get_sync_health(max_unsynced_hours=4) -> dict:
    last_success = _last_successful_sync_at()
    oldest = frappe.get_all(
        "Local Sync Queue",
        filters={"status": ["in", ["Pending", "Sent", "Failed"]]},
        fields=["name", "creation"],
        order_by="creation asc",
        limit_page_length=1,
        ignore_permissions=True,
    )
    pending_count = frappe.db.count("Local Sync Queue", {"status": ["in", ["Pending", "Sent", "Failed"]]})
    if not oldest:
        return {
            "ok": True,
            "pending_count": 0,
            "oldest_pending": None,
            "last_successful_sync_at": str(last_success) if last_success else None,
        }

    age_limit = add_to_date(now_datetime(), hours=-cint(max_unsynced_hours), as_datetime=True)
    oldest_creation = get_datetime(oldest[0].creation)
    stale = oldest_creation <= age_limit
    return {
        "ok": not stale,
        "pending_count": pending_count,
        "oldest_pending": str(oldest_creation),
        "last_successful_sync_at": str(last_success) if last_success else None,
        "stale_threshold_hours": cint(max_unsynced_hours),
    }


def ensure_sync_health(max_unsynced_hours=4) -> dict:
    health = get_sync_health(max_unsynced_hours=max_unsynced_hours)
    if not health["ok"]:
        _create_sync_queue_incident(health)
    return health


def _get_due_queue(limit):
    now = now_datetime()
    rows = frappe.get_all(
        "Local Sync Queue",
        filters={"status": ["in", ["Pending", "Failed"]]},
        fields=["name", "next_retry_at", "creation"],
        order_by="creation asc",
        limit_page_length=cint(limit) or 100,
        ignore_permissions=True,
    )
    return [row for row in rows if not row.next_retry_at or row.next_retry_at <= now]


def _post_event_batch(events, config):
    url = urljoin(config["base_url"].rstrip("/") + "/", EVENT_INGEST_ROUTE.lstrip("/"))
    response = requests.post(
        url,
        json={"events": events},
        headers={"Authorization": f"Token {config['api_token']}"},
        timeout=config["timeout"],
    )
    response.raise_for_status()
    data = response.json()
    return data.get("message", data) if isinstance(data, dict) else data


def _apply_ack(response, queue_docs):
    data = response.get("data", response) if isinstance(response, dict) else {}
    accepted = data.get("accepted") or []
    duplicates = data.get("duplicates") or []
    rejected = data.get("rejected") or []
    ok_ids = {row.get("event_id") for row in accepted + duplicates if row.get("event_id")}
    rejected_by_id = {row.get("event_id"): row.get("reason") for row in rejected if row.get("event_id")}
    acknowledged = 0
    for doc in queue_docs:
        if doc.event_id in ok_ids:
            doc.status = "Acknowledged"
            doc.last_error = None
            doc.next_retry_at = None
            doc.save(ignore_permissions=True)
            acknowledged += 1
        else:
            _mark_failed(doc, rejected_by_id.get(doc.event_id) or "missing_ack")
    return acknowledged


def _mark_failed(doc, error):
    doc.status = "Failed"
    doc.last_error = (error or "sync_failed")[:140]
    doc.next_retry_at = add_to_date(now_datetime(), seconds=_backoff_seconds(cint(doc.attempt_count)), as_datetime=True)
    doc.save(ignore_permissions=True)


def _backoff_seconds(attempt_count):
    index = max(0, min(cint(attempt_count) - 1, len(BACKOFF_SECONDS) - 1))
    return BACKOFF_SECONDS[index]


def _queue_payload(doc):
    try:
        payload = json.loads(doc.payload_json or "{}")
    except ValueError:
        payload = {}
    if payload:
        return payload
    if doc.local_event:
        return _serialize_event(frappe.get_doc("Local Attendance Event", doc.local_event))
    return {"event_id": doc.event_id}


def _serialize_event(event):
    local_session = (
        frappe.get_doc("Local Session", event.local_session)
        if event.local_session
        else None
    )
    payload_json = _event_payload_json(event)
    return {
        "event_id": event.event_id,
        "attendance_session_id": local_session.attendance_session_id if local_session else None,
        "session_id": event.session_id,
        "session_version": cint(local_session.session_version) if local_session else None,
        "local_server_id": frappe.conf.get("attendance_local_server_id") or frappe.local.site,
        "student_id": event.student_id,
        "teacher_id": event.teacher_id,
        "event_type": event.event_type,
        "event_time": str(event.event_time) if event.event_time else None,
        "attendance_state": event.attendance_state,
        "capture_source": event.capture_source,
        "payload_json": payload_json,
    }


def _event_payload_json(event) -> str | None:
    try:
        payload = json.loads(event.payload_json or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    fingerprint = _fingerprint_for_event(event.event_id)
    if fingerprint:
        payload.setdefault("fingerprint", fingerprint.fingerprint)
        payload["fingerprint_details"] = {
            "fingerprint": fingerprint.fingerprint,
            "user_agent": fingerprint.user_agent,
            "local_ip": fingerprint.local_ip,
            "screen_resolution": fingerprint.screen_resolution,
            "timezone": fingerprint.timezone,
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _fingerprint_for_event(event_id: str):
    if not event_id:
        return None
    rows = frappe.get_all(
        "Local Device Fingerprint",
        filters={"event_id": event_id},
        fields=["fingerprint", "user_agent", "local_ip", "screen_resolution", "timezone"],
        order_by="captured_at desc, creation desc",
        limit_page_length=1,
        ignore_permissions=True,
    )
    return rows[0] if rows else None


def _last_successful_sync_at():
    rows = frappe.get_all(
        "Local Sync Queue",
        filters={"status": "Acknowledged"},
        fields=["modified"],
        order_by="modified desc",
        limit_page_length=1,
        ignore_permissions=True,
    )
    return rows[0].modified if rows else None


def _create_sync_queue_incident(health):
    description = "Attendance sync queue blocked for more than 4 hours."
    existing = frappe.db.exists(
        "Local Incident",
        {"incident_type": "Sync", "status": "Open", "description": description},
    )
    if existing:
        return existing
    incident = frappe.get_doc(
        {
            "doctype": "Local Incident",
            "incident_type": "Sync",
            "severity": "High",
            "detected_at": now_datetime(),
            "description": description,
        }
    ).insert(ignore_permissions=True)
    return incident.name
