from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from attendance_edge.tests.helpers import HASH_VALUE, insert_student, insert_teacher, uid


class TestLocalUsers(FrappeTestCase):
    def test_student_import_requires_hashed_password(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local User Student",
                    "student_id": uid("ETU"),
                    "user_id": "clear@student.test",
                    "password_hash": "clear",
                    "status": "Active",
                }
            ).insert(ignore_permissions=True)

    def test_teacher_import_requires_hashed_pin_when_present(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local User Teacher",
                    "teacher_id": uid("ENS"),
                    "user_id": "clear@teacher.test",
                    "password_hash": HASH_VALUE,
                    "pin_hash": "123456",
                    "status": "Active",
                }
            ).insert(ignore_permissions=True)

    def test_student_and_teacher_local_copies_insert_with_hashes(self):
        student = insert_student()
        teacher = insert_teacher()

        self.assertEqual(student.status, "Active")
        self.assertEqual(teacher.status, "Active")
