from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from attendance_edge.tests.helpers import insert_attendance_event, uid


class TestLocalSyncQueue(FrappeTestCase):
    def test_sync_queue_accepts_event_payload_for_replay(self):
        event = insert_attendance_event()
        queue = frappe.get_doc(
            {
                "doctype": "Local Sync Queue",
                "event_id": event.event_id,
                "local_event": event.name,
                "status": "Pending",
                "attempt_count": 0,
                "payload_json": '{"event_type":"student_provisional_checkin"}',
            }
        ).insert(ignore_permissions=True)

        self.assertEqual(queue.status, "Pending")
        self.assertEqual(queue.local_event, event.name)

    def test_sync_queue_rejects_negative_attempt_count(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local Sync Queue",
                    "event_id": uid("EVT"),
                    "status": "Failed",
                    "attempt_count": -1,
                }
            ).insert(ignore_permissions=True)

    def test_sync_queue_rejects_unknown_status(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local Sync Queue",
                    "event_id": uid("EVT"),
                    "status": "Retrying",
                    "attempt_count": 0,
                }
            ).insert(ignore_permissions=True)
