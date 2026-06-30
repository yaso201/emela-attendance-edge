from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import passlibctx

from attendance_edge.offline_auth import authenticate_offline, clear_auth_rate_limit
from attendance_edge.student_app import get_student_context
from attendance_edge.student_signature import provisional_checkin
from attendance_edge.teacher_console import get_attendance_session, get_teacher_console, manual_mark_student, open_attendance_session
from attendance_edge.tests.helpers import insert_session, uid


def _insert_teacher_with_pin(teacher_id=None):
    teacher_id = teacher_id or uid("ENS-UI")
    return frappe.get_doc(
        {
            "doctype": "Local User Teacher",
            "teacher_id": teacher_id,
            "user_id": f"{teacher_id.lower()}@example.test",
            "full_name": f"Teacher {teacher_id}",
            "password_hash": passlibctx.hash("teacher-pass"),
            "pin_hash": passlibctx.hash("123456"),
            "status": "Active",
        }
    ).insert(ignore_permissions=True)


def _insert_student_with_password(student_id=None):
    student_id = student_id or uid("ETU-UI")
    return frappe.get_doc(
        {
            "doctype": "Local User Student",
            "student_id": student_id,
            "user_id": f"{student_id.lower()}@example.test",
            "full_name": f"Student {student_id}",
            "password_hash": passlibctx.hash("student-pass"),
            "status": "Active",
        }
    ).insert(ignore_permissions=True)


def _add_roster(session, student):
    return frappe.get_doc(
        {
            "doctype": "Local Session Roster",
            "local_session": session.name,
            "student": student.name,
            "student_id": student.student_id,
            "student_name": student.full_name,
            "roster_status": "Active",
        }
    ).insert(ignore_permissions=True)


class TestAttendanceTeacherUiP1E(FrappeTestCase):
    def test_teacher_console_lists_session_and_returns_qr_after_opening(self):
        teacher = _insert_teacher_with_pin()
        student = _insert_student_with_password()
        session = insert_session(teacher_id=teacher.teacher_id)
        _add_roster(session, student)
        clear_auth_rate_limit(teacher.teacher_id)

        console = get_teacher_console(teacher.teacher_id, "123456", session_date=session.session_date)
        self.assertTrue(console["ok"])
        self.assertEqual(len(console["sessions"]), 1)
        self.assertEqual(console["sessions"][0]["summary"]["total"], 1)

        detail = get_attendance_session(session.attendance_session_id, teacher.teacher_id, "123456")
        self.assertTrue(detail["ok"])
        self.assertIsNone(detail["session"]["qr_frame"])

        opened = open_attendance_session(session.attendance_session_id, teacher.teacher_id, "123456")
        self.assertTrue(opened["ok"])
        self.assertEqual(opened["session"]["status"], "Open")
        self.assertIn("<svg", opened["session"]["qr_frame"]["qr_svg"])
        self.assertNotIn("secret", opened["session"]["qr_frame"]["payload_json"].lower())

    def test_teacher_manual_mark_updates_roster_summary_and_queue(self):
        teacher = _insert_teacher_with_pin()
        student = _insert_student_with_password()
        session = insert_session(teacher_id=teacher.teacher_id)
        _add_roster(session, student)
        clear_auth_rate_limit(teacher.teacher_id)
        self.assertTrue(open_attendance_session(session.attendance_session_id, teacher.teacher_id, "123456")["ok"])

        marked = manual_mark_student(session.attendance_session_id, teacher.teacher_id, "123456", student.student_id)

        self.assertTrue(marked["ok"])
        self.assertEqual(marked["session"]["summary"]["validated"], 1)
        self.assertEqual(marked["session"]["roster"][0]["status"], "Validated")
        self.assertTrue(frappe.db.exists("Local Sync Queue", {"event_id": marked["event_id"]}))


class TestPresentLanemUiP1E(FrappeTestCase):
    def test_student_auth_context_and_provisional_checkin(self):
        teacher = _insert_teacher_with_pin()
        student = _insert_student_with_password()
        session = insert_session(teacher_id=teacher.teacher_id)
        _add_roster(session, student)

        auth = authenticate_offline(student.user_id, "student-pass", actor_type="student")
        self.assertTrue(auth["ok"])
        self.assertEqual(auth["name"], student.student_id)

        context = get_student_context(student.student_id)
        self.assertTrue(context["ok"])
        self.assertEqual(context["student"]["student_id"], student.student_id)
        self.assertEqual(context["sessions"][0]["attendance_session_id"], session.attendance_session_id)
        self.assertTrue(context["sessions"][0]["can_provisional_checkin"])

        checkin = provisional_checkin(session.attendance_session_id, student.student_id, remote_addr="192.168.50.10")
        self.assertTrue(checkin["ok"])

        context = get_student_context(student.student_id)
        self.assertEqual(context["sessions"][0]["student_status"], "Pending Validation")
