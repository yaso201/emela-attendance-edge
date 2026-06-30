from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from attendance_edge.api.replay import replay_local_events
from attendance_edge.event_sync import queue_event_for_sync
from attendance_edge.tests.helpers import insert_attendance_event, insert_session, insert_student


class TestLocalReplayP2D(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_replay_local_events_queues_matching_closure_event(self):
        session = insert_session(status="Closed")
        event = insert_attendance_event(
            session=session,
            event_type="session_auto_closed",
            attendance_state="N/A",
            capture_source="System",
        )

        result = replay_local_events(
            request_id="ATT-SYNC-ANOM-TEST",
            anomaly_type="missing_closure_event",
            attendance_session_id=session.attendance_session_id,
            sync_now=0,
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["events"], [event.event_id])
        self.assertTrue(frappe.db.exists("Local Sync Queue", {"event_id": event.event_id, "status": "Pending"}))

    def test_replay_local_events_requeues_acknowledged_event_and_can_sync_now(self):
        student = insert_student()
        session = insert_session(status="Closed")
        event = insert_attendance_event(
            session=session,
            event_type="student_signature_received",
            student_id=student.student_id,
            attendance_state="Validated",
            capture_source="Student QR",
        )
        queue_name = queue_event_for_sync(event)
        frappe.db.set_value(
            "Local Sync Queue",
            queue_name,
            {
                "status": "Acknowledged",
                "attempt_count": 3,
                "last_error": "old",
            },
        )

        with patch(
            "attendance_edge.api.replay.push_pending_events_to_central",
            return_value={"status": "sent", "sent": 1, "acknowledged": 1, "failed": 0},
        ) as push:
            result = replay_local_events(
                request_id="ATT-SYNC-ANOM-TEST",
                anomaly_type="missing_student_attendance",
                attendance_session_id=session.attendance_session_id,
                student_id=student.student_id,
                sync_now=1,
            )

        self.assertEqual(result["status"], "synced")
        push.assert_called_once_with(limit=1)
        queue = frappe.get_doc("Local Sync Queue", queue_name)
        self.assertEqual(queue.status, "Pending")
        self.assertEqual(queue.attempt_count, 0)
        self.assertIsNone(queue.last_error)

    def test_replay_local_events_reports_no_events(self):
        session = insert_session(status="Closed")

        result = replay_local_events(
            request_id="ATT-SYNC-ANOM-TEST",
            anomaly_type="missing_closure_event",
            attendance_session_id=session.attendance_session_id,
            sync_now=0,
        )

        self.assertEqual(result["status"], "no_events")
        self.assertEqual(result["queued"], 0)
