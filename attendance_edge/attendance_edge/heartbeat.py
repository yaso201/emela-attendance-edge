from __future__ import annotations

import socket
import time
from urllib.parse import urljoin

import frappe
import requests
from frappe.utils import cint, now_datetime

from attendance_edge.identity_sync import _get_central_config


HEARTBEAT_ROUTE = "/api/method/portal_app.api.attendance_heartbeat.ingest_heartbeat"


@frappe.whitelist()
def get_local_health_snapshot() -> dict:
    queue_depth = _queue_depth()
    open_incidents = _open_incident_counts()
    return {
        "local_server_id": frappe.conf.get("attendance_local_server_id") or frappe.local.site,
        "site_name": frappe.local.site,
        "host_name": socket.gethostname(),
        "ip_address": _local_ip_address(),
        "app_version": _app_version(),
        "heartbeat_time": now_datetime().isoformat(),
        "status": _overall_status(queue_depth, open_incidents),
        "freshness_threshold_minutes": cint(frappe.conf.get("attendance_heartbeat_freshness_minutes") or 15),
        "ntp_offset_seconds": _ntp_offset_seconds(),
        "queue_depth": queue_depth,
        "last_sync_at": _last_successful_sync_at(),
        "details": {
            "open_incidents": open_incidents,
            "open_sessions": frappe.db.count("Local Session", {"status": "Open"}),
            "pending_sessions": frappe.db.count("Local Session", {"status": "Pending"}),
        },
    }


def send_heartbeat_to_central() -> dict:
    config = _get_central_config()
    url = urljoin(config["base_url"].rstrip("/") + "/", HEARTBEAT_ROUTE.lstrip("/"))
    payload = get_local_health_snapshot()
    started = time.monotonic()

    try:
        response = requests.post(
            url,
            json={"payload": payload},
            headers={"Authorization": f"Token {config['api_token']}"},
            timeout=config["timeout"],
        )
        response.raise_for_status()
        latency_ms = int((time.monotonic() - started) * 1000)
        _insert_heartbeat_log("Success", url, latency_ms, "heartbeat_sent")
        return {"ok": True, "status": "sent", "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        message = str(exc)[:140]
        _insert_heartbeat_log("Failed", url, latency_ms, message)
        _record_heartbeat_incident(message)
        return {"ok": False, "status": "failed", "error": message, "latency_ms": latency_ms}


def _queue_depth() -> int:
    return frappe.db.count("Local Sync Queue", {"status": ["in", ["Pending", "Sent", "Failed"]]})


def _last_successful_sync_at():
    rows = frappe.get_all(
        "Local Sync Queue",
        filters={"status": "Acknowledged"},
        fields=["modified"],
        order_by="modified desc",
        limit_page_length=1,
        ignore_permissions=True,
    )
    return rows[0].modified.isoformat() if rows else None


def _open_incident_counts() -> dict:
    rows = frappe.get_all(
        "Local Incident",
        filters={"status": "Open"},
        fields=["severity"],
        ignore_permissions=True,
    )
    counts = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    for row in rows:
        counts[row.severity] = counts.get(row.severity, 0) + 1
    return counts


def _overall_status(queue_depth: int, open_incidents: dict) -> str:
    if open_incidents.get("Critical"):
        return "Failed"
    if open_incidents.get("High") or queue_depth:
        return "Warning"
    return "Success"


def _local_ip_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _app_version():
    try:
        return frappe.get_attr("attendance_edge.__version__")
    except Exception:
        return "0.0.1"


def _ntp_offset_seconds():
    value = frappe.conf.get("attendance_ntp_offset_seconds")
    return float(value) if value not in (None, "") else None


def _insert_heartbeat_log(status: str, target_url: str, latency_ms: int, message: str):
    return frappe.get_doc(
        {
            "doctype": "Local Heartbeat Log",
            "heartbeat_time": now_datetime(),
            "status": status,
            "target_url": target_url,
            "latency_ms": max(0, latency_ms),
            "message": message,
        }
    ).insert(ignore_permissions=True)


def _record_heartbeat_incident(message: str):
    description = "Attendance heartbeat emission failed."
    existing = frappe.db.exists(
        "Local Incident",
        {"incident_type": "Network", "status": "Open", "description": description},
    )
    if existing:
        return existing
    return frappe.get_doc(
        {
            "doctype": "Local Incident",
            "incident_type": "Network",
            "severity": "High",
            "detected_at": now_datetime(),
            "description": description,
        }
    ).insert(ignore_permissions=True).name
