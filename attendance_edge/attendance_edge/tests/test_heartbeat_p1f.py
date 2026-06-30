from __future__ import annotations

from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from attendance_edge.heartbeat import get_local_health_snapshot, send_heartbeat_to_central
from attendance_edge.tests.helpers import insert_attendance_event


class TestHeartbeatP1F(FrappeTestCase):
    def test_local_health_snapshot_contains_queue_and_incidents(self):
        event = insert_attendance_event()
        frappe.get_doc(
            {
                "doctype": "Local Sync Queue",
                "event_id": event.event_id,
                "local_event": event.name,
                "status": "Pending",
                "attempt_count": 0,
                "payload_json": "{}",
            }
        ).insert(ignore_permissions=True)
        frappe.get_doc(
            {
                "doctype": "Local Incident",
                "incident_type": "Sync",
                "severity": "High",
                "detected_at": frappe.utils.now_datetime(),
                "description": "Queue bloquee",
            }
        ).insert(ignore_permissions=True)

        snapshot = get_local_health_snapshot()

        self.assertEqual(snapshot["queue_depth"], 1)
        self.assertEqual(snapshot["status"], "Warning")
        self.assertEqual(snapshot["details"]["open_incidents"]["High"], 1)

    @patch("attendance_edge.heartbeat.requests.post")
    @patch("attendance_edge.heartbeat._get_central_config")
    def test_send_heartbeat_logs_success(self, config, post):
        config.return_value = {"base_url": "http://central.test", "api_token": "secret", "timeout": 5}
        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        result = send_heartbeat_to_central()

        self.assertTrue(result["ok"])
        self.assertTrue(frappe.db.exists("Local Heartbeat Log", {"status": "Success"}))

    @patch("attendance_edge.heartbeat.requests.post")
    @patch("attendance_edge.heartbeat._get_central_config")
    def test_send_heartbeat_logs_failure_and_incident(self, config, post):
        config.return_value = {"base_url": "http://central.test", "api_token": "secret", "timeout": 5}
        post.side_effect = RuntimeError("network down")

        result = send_heartbeat_to_central()

        self.assertFalse(result["ok"])
        self.assertTrue(frappe.db.exists("Local Heartbeat Log", {"status": "Failed"}))
        self.assertTrue(
            frappe.db.exists(
                "Local Incident",
                {"incident_type": "Network", "status": "Open", "description": "Attendance heartbeat emission failed."},
            )
        )
