from __future__ import annotations

import frappe
from frappe.utils import get_datetime, now_datetime


HASH_VALUE = "x" * 64


def uid(prefix: str) -> str:
    return f"{prefix}-{frappe.generate_hash(length=10)}"


def insert_student(student_id: str | None = None):
    student_id = student_id or uid("ETU")
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


def insert_teacher(teacher_id: str | None = None):
    teacher_id = teacher_id or uid("ENS")
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


def insert_session(**overrides):
    data = {
        "doctype": "Local Session",
        "attendance_session_id": uid("LSESS"),
        "session_id": uid("PLAN"),
        "session_version": 1,
        "module_code": "MATH-101",
        "student_group": "LIS-L1-A",
        "teacher_id": uid("ENS"),
        "session_date": "2026-05-04",
        "planned_start": get_datetime("2026-05-04 08:00:00"),
        "planned_end": get_datetime("2026-05-04 10:00:00"),
        "room": "B12",
        "status": "Pending",
    }
    data.update(overrides)
    return frappe.get_doc(data).insert(ignore_permissions=True)


def insert_attendance_event(session=None, **overrides):
    session = session or insert_session()
    data = {
        "doctype": "Local Attendance Event",
        "event_id": uid("EVT"),
        "local_session": session.name,
        "session_id": session.session_id,
        "event_type": "student_provisional_checkin",
        "event_time": now_datetime(),
        "attendance_state": "Pending Validation",
        "capture_source": "Student Provisional",
    }
    data.update(overrides)
    return frappe.get_doc(data).insert(ignore_permissions=True)
