from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from attendance_edge import hooks
from attendance_edge.event_sync import _apply_ack, ensure_sync_health, queue_event_for_sync
from attendance_edge.planning_sync import sync_planning_payload
from attendance_edge.tests.helpers import insert_attendance_event, insert_student, uid


class TestPlanningSyncP1D(FrappeTestCase):
    def test_planning_payload_upserts_session_roster_and_leave(self):
        student = insert_student(uid("ETU-P1D"))
        payload = {
            "data": [
                {
                    "attendance_session_id": uid("ATT-P1D"),
                    "session_id": uid("PLAN-P1D"),
                    "session_version": 1,
                    "module_code": "MATH-101",
                    "student_group": "LIS-L1-A",
                    "teacher_id": "ENS-P1D",
                    "replacement_teacher_id": "ENS-REM-P1D",
                    "session_date": "2026-05-04",
                    "planned_start": "2026-05-04 08:00:00",
                    "planned_end": "2026-05-04 10:00:00",
                    "room": "B12",
                    "status": "Pending",
                    "roster": [
                        {
                            "student_id": student.student_id,
                            "student_name": student.full_name,
                            "roster_status": "Active",
                        }
                    ],
                    "leaves": [
                        {
                            "leave_id": uid("LEAVE-P1D"),
                            "student_id": student.student_id,
                            "starts_at": "2026-05-04 00:00:00",
                            "ends_at": "2026-05-04 23:59:59",
                            "covered_sessions": ["ATT-P1D"],
                            "approved_by": "service.peda@example.test",
                            "approved_at": "2026-05-03 12:00:00",
                            "source_version": "2026-05-03 12:00:00",
                        }
                    ],
                }
            ]
        }

        result = sync_planning_payload(payload)

        self.assertEqual(result["sessions_created"], 1)
        self.assertEqual(result["roster_upserts"], 1)
        self.assertEqual(result["leaves_upserted"], 1)
        session_name = frappe.db.get_value("Local Session", {"session_id": payload["data"][0]["session_id"]}, "name")
        self.assertTrue(session_name)
        replacement_teacher = frappe.db.get_value("Local Session", session_name, "replacement_teacher_id")
        self.assertEqual(replacement_teacher, "ENS-REM-P1D")
        roster = frappe.get_all("Local Session Roster", filters={"local_session": session_name}, fields=["student_id"])
        self.assertEqual(roster[0].student_id, student.student_id)

    def test_planning_payload_marks_missing_roster_as_removed(self):
        student = insert_student(uid("ETU-P1D"))
        attendance_session_id = uid("ATT-P1D")
        base = {
            "attendance_session_id": attendance_session_id,
            "session_id": uid("PLAN-P1D"),
            "session_version": 1,
            "teacher_id": "ENS-P1D",
            "session_date": "2026-05-04",
            "planned_start": "2026-05-04 08:00:00",
            "planned_end": "2026-05-04 10:00:00",
            "status": "Pending",
        }
        sync_planning_payload({"data": [{**base, "roster": [{"student_id": student.student_id}]}]})
        sync_planning_payload({"data": [{**base, "session_version": 2, "roster": []}]})

        session_name = frappe.db.get_value("Local Session", {"attendance_session_id": attendance_session_id}, "name")
        roster_status = frappe.db.get_value(
            "Local Session Roster",
            {"local_session": session_name, "student_id": student.student_id},
            "roster_status",
        )
        self.assertEqual(roster_status, "Removed")

    def test_open_session_gets_planning_sync_flag_on_change(self):
        attendance_session_id = uid("ATT-P1D")
        session_id = uid("PLAN-P1D")
        sync_planning_payload(
            {
                "data": [
                    {
                        "attendance_session_id": attendance_session_id,
                        "session_id": session_id,
                        "session_version": 1,
                        "teacher_id": "ENS-P1D",
                        "session_date": "2026-05-04",
                        "planned_start": "2026-05-04 08:00:00",
                        "planned_end": "2026-05-04 10:00:00",
                        "status": "Pending",
                    }
                ]
            }
        )
        local_name = frappe.db.get_value("Local Session", {"attendance_session_id": attendance_session_id}, "name")
        local = frappe.get_doc("Local Session", local_name)
        local.status = "Open"
        local.save(ignore_permissions=True)

        sync_planning_payload(
            {
                "data": [
                    {
                        "attendance_session_id": attendance_session_id,
                        "session_id": session_id,
                        "session_version": 2,
                        "teacher_id": "ENS-P1D",
                        "session_date": "2026-05-04",
                        "planned_start": "2026-05-04 08:30:00",
                        "planned_end": "2026-05-04 10:30:00",
                        "status": "Pending",
                    }
                ]
            }
        )

        local.reload()
        self.assertEqual(local.planning_sync_updated, 1)
        self.assertEqual(get_datetime(local.planned_start), get_datetime("2026-05-04 08:30:00"))


class TestEventSyncP1D(FrappeTestCase):
    def test_queue_event_for_sync_includes_session_version_and_acknowledges(self):
        event = insert_attendance_event()
        queue_name = queue_event_for_sync(event)

        queue = frappe.get_doc("Local Sync Queue", queue_name)
        self.assertEqual(queue.status, "Pending")
        payload = json.loads(queue.payload_json)
        self.assertEqual(payload["session_version"], 1)

        acknowledged = _apply_ack(
            {"data": {"accepted": [{"event_id": event.event_id}], "duplicates": [], "rejected": []}},
            [queue],
        )

        queue.reload()
        self.assertEqual(acknowledged, 1)
        self.assertEqual(queue.status, "Acknowledged")

    def test_sync_health_creates_incident_when_queue_is_stale(self):
        event = insert_attendance_event()
        queue_name = queue_event_for_sync(event)
        frappe.db.set_value(
            "Local Sync Queue",
            queue_name,
            "creation",
            add_to_date(now_datetime(), hours=-5, as_datetime=True),
            update_modified=False,
        )

        health = ensure_sync_health(max_unsynced_hours=4)

        self.assertFalse(health["ok"])
        self.assertTrue(
            frappe.db.exists(
                "Local Incident",
                {
                    "incident_type": "Sync",
                    "status": "Open",
                    "description": "Attendance sync queue blocked for more than 4 hours.",
                },
            )
        )

    def test_scheduler_hooks_cover_fast_polling_daily_preload_and_queue_monitor(self):
        self.assertIn("*/5 * * * *", hooks.scheduler_events["cron"])
        self.assertIn(
            "attendance_edge.scheduler.run_daily_planning_preload",
            hooks.scheduler_events["daily"],
        )
        self.assertIn(
            "attendance_edge.scheduler.monitor_sync_queue",
            hooks.scheduler_events["hourly"],
        )
