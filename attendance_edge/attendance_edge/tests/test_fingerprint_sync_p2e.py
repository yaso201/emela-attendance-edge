from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from attendance_edge.event_sync import queue_event_for_sync
from attendance_edge.tests.helpers import insert_attendance_event, insert_session, insert_student


class TestFingerprintSyncP2E(FrappeTestCase):
    def test_sync_payload_includes_fingerprint_details_without_mac(self):
        student = insert_student()
        session = insert_session(status="Open")
        event = insert_attendance_event(
            session=session,
            event_type="student_signature_received",
            student_id=student.student_id,
            attendance_state="Validated",
            capture_source="Student QR",
            payload_json=json.dumps({"fingerprint": "fp-local-p2e"}),
        )
        frappe.get_doc(
            {
                "doctype": "Local Device Fingerprint",
                "student_id": student.student_id,
                "event_id": event.event_id,
                "fingerprint": "fp-local-p2e",
                "user_agent": "pytest",
                "local_ip": "192.168.50.42",
                "screen_resolution": "390x844",
                "timezone": "Africa/Porto-Novo",
                "captured_at": now_datetime(),
            }
        ).insert(ignore_permissions=True)

        queue_name = queue_event_for_sync(event)

        payload = json.loads(frappe.db.get_value("Local Sync Queue", queue_name, "payload_json"))
        event_payload = json.loads(payload["payload_json"])
        self.assertEqual(event_payload["fingerprint"], "fp-local-p2e")
        self.assertEqual(event_payload["fingerprint_details"]["local_ip"], "192.168.50.42")
        self.assertNotIn("mac", json.dumps(event_payload).lower())
