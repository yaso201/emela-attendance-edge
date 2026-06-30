from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from attendance_edge.tests.helpers import insert_attendance_event, insert_session, uid


class TestLocalAttendanceEvent(FrappeTestCase):
    def test_event_records_student_provisional_checkin(self):
        event = insert_attendance_event(student_id=uid("ETU"))

        self.assertEqual(event.event_type, "student_provisional_checkin")
        self.assertEqual(event.attendance_state, "Pending Validation")
        self.assertEqual(event.capture_source, "Student Provisional")

    def test_event_rejects_unknown_type(self):
        session = insert_session()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local Attendance Event",
                    "event_id": uid("EVT"),
                    "local_session": session.name,
                    "session_id": session.session_id,
                    "event_type": "qr_scanned",
                    "event_time": now_datetime(),
                }
            ).insert(ignore_permissions=True)

    def test_event_remains_append_only_after_insert(self):
        event = insert_attendance_event()
        event.payload_json = "{}"
        with self.assertRaises(frappe.ValidationError):
            event.save(ignore_permissions=True)
