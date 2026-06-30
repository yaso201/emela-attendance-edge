from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_datetime, now_datetime


HASH_VALUE = "x" * 64


def _uid(prefix: str) -> str:
    return f"{prefix}-{frappe.generate_hash(length=10)}"


def _insert_student(student_id: str | None = None):
    student_id = student_id or _uid("ETU")
    return frappe.get_doc(
        {
            "doctype": "Local User Student",
            "student_id": student_id,
            "user_id": f"{student_id.lower()}@example.test",
            "full_name": f"Student {student_id}",
            "password_hash": HASH_VALUE,
            "status": "Active",
        }
    ).insert(ignore_permissions=True)


def _insert_teacher(teacher_id: str | None = None):
    teacher_id = teacher_id or _uid("ENS")
    return frappe.get_doc(
        {
            "doctype": "Local User Teacher",
            "teacher_id": teacher_id,
            "user_id": f"{teacher_id.lower()}@example.test",
            "full_name": f"Teacher {teacher_id}",
            "password_hash": HASH_VALUE,
            "pin_hash": HASH_VALUE,
            "status": "Active",
        }
    ).insert(ignore_permissions=True)


def _insert_session():
    start = get_datetime("2026-05-04 08:00:00")
    end = get_datetime("2026-05-04 10:00:00")
    return frappe.get_doc(
        {
            "doctype": "Local Session",
            "attendance_session_id": _uid("LSESS"),
            "session_id": _uid("PLAN"),
            "session_version": 1,
            "module_code": "MATH-101",
            "student_group": "LIS-L1-A",
            "teacher_id": _uid("ENS"),
            "session_date": "2026-05-04",
            "planned_start": start,
            "planned_end": end,
            "room": "B12",
            "status": "Pending",
        }
    ).insert(ignore_permissions=True)


class TestLocalAttendanceDoctypes(FrappeTestCase):
    def test_p1a_doctypes_are_installed(self):
        for doctype in [
            "Local User Student",
            "Local User Teacher",
            "Local Session",
            "Local Session Roster",
            "Local Leave",
            "Local Attendance Event",
            "Local Device Fingerprint",
            "Local Sync Queue",
            "Local Heartbeat Log",
            "Local Incident",
        ]:
            self.assertTrue(frappe.db.exists("DocType", doctype), doctype)

    def test_student_password_hash_rejects_clear_value(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local User Student",
                    "student_id": _uid("ETU"),
                    "user_id": "clear@student.test",
                    "password_hash": "clear",
                    "status": "Active",
                }
            ).insert(ignore_permissions=True)

    def test_teacher_hashes_reject_clear_values(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local User Teacher",
                    "teacher_id": _uid("ENS"),
                    "user_id": "clear@teacher.test",
                    "password_hash": HASH_VALUE,
                    "pin_hash": "123456",
                    "status": "Active",
                }
            ).insert(ignore_permissions=True)

    def test_local_session_validates_dates_and_flags(self):
        session = _insert_session()
        session.paper_mode_used = 1
        session.planning_conflict_detected = 1
        session.save(ignore_permissions=True)

        loaded = frappe.get_doc("Local Session", session.name)
        self.assertEqual(loaded.paper_mode_used, 1)
        self.assertEqual(loaded.planning_conflict_detected, 1)

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local Session",
                    "attendance_session_id": _uid("LSESS"),
                    "session_id": _uid("PLAN"),
                    "session_date": "2026-05-04",
                    "planned_start": "2026-05-04 10:00:00",
                    "planned_end": "2026-05-04 08:00:00",
                    "status": "Pending",
                }
            ).insert(ignore_permissions=True)

    def test_roster_rejects_duplicate_student_in_session(self):
        session = _insert_session()
        student = _insert_student()
        payload = {
            "doctype": "Local Session Roster",
            "local_session": session.name,
            "student": student.name,
            "student_id": student.student_id,
            "student_name": student.full_name,
            "roster_status": "Active",
        }
        frappe.get_doc(payload).insert(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(payload).insert(ignore_permissions=True)

    def test_leave_date_range_and_coverage(self):
        student = _insert_student()
        leave = frappe.get_doc(
            {
                "doctype": "Local Leave",
                "leave_id": _uid("LEAVE"),
                "student_id": student.student_id,
                "starts_at": now_datetime(),
                "ends_at": add_days(now_datetime(), 1),
                "approved_by": "service.peda@example.test",
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(leave.student_id, student.student_id)

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local Leave",
                    "leave_id": _uid("LEAVE"),
                    "student_id": student.student_id,
                    "starts_at": "2026-05-05 10:00:00",
                    "ends_at": "2026-05-04 10:00:00",
                }
            ).insert(ignore_permissions=True)

    def test_attendance_event_is_unique_and_append_only(self):
        session = _insert_session()
        event_id = _uid("EVT")
        event = frappe.get_doc(
            {
                "doctype": "Local Attendance Event",
                "event_id": event_id,
                "local_session": session.name,
                "session_id": session.session_id,
                "event_type": "student_provisional_checkin",
                "event_time": now_datetime(),
                "attendance_state": "Pending Validation",
                "capture_source": "Student Provisional",
            }
        ).insert(ignore_permissions=True)

        with self.assertRaises(frappe.DuplicateEntryError):
            frappe.get_doc(
                {
                    "doctype": "Local Attendance Event",
                    "event_id": event_id,
                    "session_id": session.session_id,
                    "event_type": "student_provisional_checkin",
                    "event_time": now_datetime(),
                }
            ).insert(ignore_permissions=True)

        loaded = frappe.get_doc("Local Attendance Event", event.name)
        loaded.payload_json = "{}"
        with self.assertRaises(frappe.ValidationError):
            loaded.save(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            loaded.delete(ignore_permissions=True)

    def test_fingerprint_sync_queue_heartbeat_and_incident(self):
        event_id = _uid("EVT")
        fingerprint = frappe.get_doc(
            {
                "doctype": "Local Device Fingerprint",
                "student_id": _uid("ETU"),
                "event_id": event_id,
                "fingerprint": _uid("FP"),
                "user_agent": "pytest",
                "local_ip": "192.168.50.10",
                "screen_resolution": "390x844",
                "timezone": "Africa/Porto-Novo",
                "captured_at": now_datetime(),
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(fingerprint.name)

        queue = frappe.get_doc(
            {
                "doctype": "Local Sync Queue",
                "event_id": event_id,
                "status": "Pending",
                "attempt_count": 0,
                "payload_json": "{}",
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(queue.status, "Pending")

        heartbeat = frappe.get_doc(
            {
                "doctype": "Local Heartbeat Log",
                "heartbeat_time": now_datetime(),
                "status": "Success",
                "target_url": "http://127.0.0.1:8000",
                "latency_ms": 10,
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(heartbeat.name)

        incident = frappe.get_doc(
            {
                "doctype": "Local Incident",
                "incident_type": "Sync",
                "severity": "High",
                "detected_at": now_datetime(),
                "description": "Test incident",
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(incident.severity, "High")
