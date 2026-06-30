from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from attendance_edge.tests.helpers import insert_student, uid


class TestLocalLeave(FrappeTestCase):
    def test_leave_records_approved_local_coverage_window(self):
        student = insert_student()
        leave = frappe.get_doc(
            {
                "doctype": "Local Leave",
                "leave_id": uid("LEAVE"),
                "student_id": student.student_id,
                "starts_at": now_datetime(),
                "ends_at": add_days(now_datetime(), 1),
                "approved_by": "service.peda@example.test",
            }
        ).insert(ignore_permissions=True)

        self.assertEqual(leave.student_id, student.student_id)
        self.assertEqual(leave.approved_by, "service.peda@example.test")

    def test_leave_rejects_inverted_dates(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local Leave",
                    "leave_id": uid("LEAVE"),
                    "student_id": uid("ETU"),
                    "starts_at": "2026-05-05 10:00:00",
                    "ends_at": "2026-05-04 10:00:00",
                }
            ).insert(ignore_permissions=True)
