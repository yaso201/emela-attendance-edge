from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import frappe
from frappe.utils import add_months, cint, get_datetime, now_datetime


DEFAULT_LOCAL_RETENTION_YEARS = {
    "local_attendance_event": 3,
    "local_device_fingerprint": 2,
    "local_sync_queue": 3,
    "local_heartbeat_log": 3,
    "local_incident": 3,
}


@dataclass(frozen=True)
class LocalRetentionRule:
    target: str
    target_doctype: str
    date_field: str
    retention_key: str
    filters: tuple[tuple[str, str, object], ...] = ()


LOCAL_RETENTION_RULES = (
    LocalRetentionRule(
        target="local_attendance_event",
        target_doctype="Local Attendance Event",
        date_field="event_time",
        retention_key="local_attendance_event",
    ),
    LocalRetentionRule(
        target="local_device_fingerprint",
        target_doctype="Local Device Fingerprint",
        date_field="captured_at",
        retention_key="local_device_fingerprint",
    ),
    LocalRetentionRule(
        target="local_sync_queue",
        target_doctype="Local Sync Queue",
        date_field="modified",
        retention_key="local_sync_queue",
        filters=(("status", "in", ("Sent", "Acknowledged")),),
    ),
    LocalRetentionRule(
        target="local_heartbeat_log",
        target_doctype="Local Heartbeat Log",
        date_field="heartbeat_time",
        retention_key="local_heartbeat_log",
    ),
    LocalRetentionRule(
        target="local_incident",
        target_doctype="Local Incident",
        date_field="detected_at",
        retention_key="local_incident",
    ),
)


def run_monthly_local_retention_purge() -> dict:
    enabled = cint(frappe.conf.get("attendance_local_retention_purge_enabled", 0))
    return run_local_retention_purge(dry_run=not bool(enabled))


def run_local_retention_purge(dry_run: bool = True, reference_time=None, limit_per_rule: int = 500) -> dict:
    started_at = now_datetime()
    purge_run_id = f"LOCAL-PURGE-{started_at.strftime('%Y%m%d%H%M%S')}-{frappe.generate_hash(length=8)}"
    reference_dt = get_datetime(reference_time) if reference_time else started_at
    dry_run = bool(cint(dry_run))
    limit_per_rule = max(1, cint(limit_per_rule) or 500)
    results = []
    for rule in LOCAL_RETENTION_RULES:
        if not _doctype_ready(rule.target_doctype):
            results.append(_skipped_result(rule, "doctype_missing", dry_run))
            continue
        cutoff = add_months(reference_dt, -12 * _retention_years(rule.retention_key))
        try:
            names = _expired_names(rule, cutoff, limit_per_rule)
            if names and not dry_run:
                frappe.db.delete(rule.target_doctype, {"name": ["in", names]})
            _insert_purge_log(
                purge_run_id=purge_run_id,
                rule=rule,
                started_at=started_at,
                dry_run=dry_run,
                cutoff=cutoff,
                names=names,
                status="Success",
                details={"limit_per_rule": limit_per_rule},
            )
            results.append(
                {
                    "target": rule.target,
                    "target_doctype": rule.target_doctype,
                    "cutoff_datetime": str(cutoff),
                    "retention_years": _retention_years(rule.retention_key),
                    "record_count": len(names),
                    "dry_run": dry_run,
                    "status": "Success",
                }
            )
        except Exception as exc:
            _insert_purge_log(
                purge_run_id=purge_run_id,
                rule=rule,
                started_at=started_at,
                dry_run=dry_run,
                cutoff=cutoff,
                names=[],
                status="Failed",
                error=str(exc),
            )
            results.append(
                {
                    "target": rule.target,
                    "target_doctype": rule.target_doctype,
                    "record_count": 0,
                    "dry_run": dry_run,
                    "status": "Failed",
                    "error": str(exc),
                }
            )
    return {"purge_run_id": purge_run_id, "dry_run": dry_run, "results": results}


def _retention_years(key: str) -> int:
    fieldname = f"attendance_retention_{key}_years"
    return max(1, cint(frappe.conf.get(fieldname, DEFAULT_LOCAL_RETENTION_YEARS[key])) or DEFAULT_LOCAL_RETENTION_YEARS[key])


def _doctype_ready(doctype: str) -> bool:
    return bool(frappe.db.exists("DocType", doctype))


def _expired_names(rule: LocalRetentionRule, cutoff, limit_per_rule: int) -> list[str]:
    filters = [[rule.target_doctype, rule.date_field, "<", cutoff]]
    filters.extend([[rule.target_doctype, field, operator, value] for field, operator, value in rule.filters])
    return frappe.get_all(
        rule.target_doctype,
        filters=filters,
        pluck="name",
        order_by=f"{rule.date_field} asc",
        limit_page_length=limit_per_rule,
        ignore_permissions=True,
    )


def _insert_purge_log(
    *,
    purge_run_id: str,
    rule: LocalRetentionRule,
    started_at,
    dry_run: bool,
    cutoff,
    names: list[str],
    status: str,
    details: dict | None = None,
    error: str | None = None,
) -> None:
    if not _doctype_ready("Local Retention Purge Log"):
        return
    frappe.get_doc(
        {
            "doctype": "Local Retention Purge Log",
            "purge_log_id": f"{purge_run_id}-{rule.target}",
            "purge_run_id": purge_run_id,
            "started_at": started_at,
            "completed_at": now_datetime(),
            "initiated_by": frappe.session.user,
            "dry_run": 1 if dry_run else 0,
            "status": status,
            "target": rule.target,
            "target_doctype": rule.target_doctype,
            "retention_years": _retention_years(rule.retention_key),
            "cutoff_datetime": cutoff,
            "record_count": len(names),
            "records_hash": _records_hash(names),
            "details_json": json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            "error": error,
        }
    ).insert(ignore_permissions=True, ignore_links=True)


def _records_hash(names: list[str]) -> str | None:
    if not names:
        return None
    return hashlib.sha256("\n".join(sorted(names)).encode("utf-8")).hexdigest()


def _skipped_result(rule: LocalRetentionRule, reason: str, dry_run: bool) -> dict:
    return {
        "target": rule.target,
        "target_doctype": rule.target_doctype,
        "record_count": 0,
        "dry_run": dry_run,
        "status": "Skipped",
        "reason": reason,
    }
