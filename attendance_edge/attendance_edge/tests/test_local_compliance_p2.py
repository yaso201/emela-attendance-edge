from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime

from attendance_edge import hooks
from attendance_edge.compliance import run_local_retention_purge
from attendance_edge.tests.helpers import insert_attendance_event, insert_session


class TestLocalComplianceP2(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_local_dry_run_reports_expired_events_without_deleting(self):
        session = insert_session()
        old_event = insert_attendance_event(session=session, event_time=get_datetime("2022-05-01 08:00:00"))

        result = run_local_retention_purge(
            dry_run=True,
            reference_time="2026-05-03 00:00:00",
            limit_per_rule=1000,
        )

        local_event_result = _result_for(result, "local_attendance_event")
        self.assertEqual(local_event_result["status"], "Success")
        self.assertGreaterEqual(local_event_result["record_count"], 1)
        self.assertTrue(frappe.db.exists("Local Attendance Event", old_event.name))

    def test_local_purge_deletes_expired_events_and_logs_trace(self):
        session = insert_session()
        old_event = insert_attendance_event(session=session, event_time=get_datetime("2022-05-01 08:00:00"))
        recent_event = insert_attendance_event(session=session, event_time=get_datetime("2026-04-01 08:00:00"))

        result = run_local_retention_purge(
            dry_run=False,
            reference_time="2026-05-03 00:00:00",
            limit_per_rule=1000,
        )

        self.assertFalse(frappe.db.exists("Local Attendance Event", old_event.name))
        self.assertTrue(frappe.db.exists("Local Attendance Event", recent_event.name))
        self.assertTrue(
            frappe.db.exists(
                "Local Retention Purge Log",
                {
                    "purge_run_id": result["purge_run_id"],
                    "target": "local_attendance_event",
                    "dry_run": 0,
                    "status": "Success",
                },
            )
        )

    def test_local_compliance_scheduler_hook_is_registered(self):
        self.assertIn("0 4 1 * *", hooks.scheduler_events["cron"])
        self.assertIn(
            "attendance_edge.compliance.run_monthly_local_retention_purge",
            hooks.scheduler_events["cron"]["0 4 1 * *"],
        )


def _result_for(result: dict, target: str) -> dict:
    for row in result["results"]:
        if row["target"] == target:
            return row
    raise AssertionError(f"Missing purge result for {target}")
