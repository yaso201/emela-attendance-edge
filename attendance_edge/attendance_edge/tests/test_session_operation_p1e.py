from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime
from frappe.utils.password import get_decrypted_password, passlibctx

from attendance_edge.offline_auth import clear_auth_rate_limit
from attendance_edge.session_ops import close_due_sessions, open_session, purge_expired_session_secrets
from attendance_edge.student_signature import provisional_checkin, submit_qr_signature
from attendance_edge.tests.helpers import insert_session, insert_student, uid
from attendance_edge.totp_qr import calculate_totp_bytes, get_qr_frame, validate_qr_payload


def _insert_teacher_with_pin(teacher_id=None):
    teacher_id = teacher_id or uid("ENS-P1E")
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


def _fingerprint():
    return {
        "fingerprint": uid("FP-P1E"),
        "user_agent": "pytest",
        "screen_resolution": "390x844",
        "timezone": "Africa/Porto-Novo",
    }


class TestTotpQrP1E(FrappeTestCase):
    def test_totp_matches_rfc_6238_vector(self):
        secret = b"12345678901234567890"
        self.assertEqual(calculate_totp_bytes(secret, for_time=59, step_seconds=30, digits=8), "94287082")
        self.assertEqual(calculate_totp_bytes(secret, for_time=1111111109, step_seconds=30, digits=8), "07081804")

    def test_open_session_generates_secret_and_server_side_qr_payload(self):
        teacher = _insert_teacher_with_pin()
        session = insert_session(teacher_id=teacher.teacher_id)
        clear_auth_rate_limit(teacher.teacher_id)

        result = open_session(session.attendance_session_id, teacher.teacher_id, "123456")

        self.assertTrue(result["ok"])
        session.reload()
        self.assertEqual(session.status, "Open")
        secret = get_decrypted_password("Local Session", session.name, "secret_session", raise_exception=False)
        self.assertEqual(len(secret), 64)

        frame = get_qr_frame(session.attendance_session_id)
        self.assertIn("<svg", frame["qr_svg"])
        self.assertNotIn("secret", frame["payload_json"].lower())
        valid, reason = validate_qr_payload(session, frame["payload"])
        self.assertTrue(valid, reason)

    def test_replacement_teacher_can_open_assigned_session(self):
        titular = _insert_teacher_with_pin()
        replacement = _insert_teacher_with_pin()
        session = insert_session(
            teacher_id=titular.teacher_id,
            replacement_teacher_id=replacement.teacher_id,
        )
        clear_auth_rate_limit(replacement.teacher_id)

        forbidden = open_session(session.attendance_session_id, uid("ENS-OTHER-P1E"), "123456")
        self.assertFalse(forbidden["ok"])
        self.assertEqual(forbidden["status"], "forbidden_teacher")

        result = open_session(session.attendance_session_id, replacement.teacher_id, "123456")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "opened")
        session.reload()
        self.assertEqual(session.status, "Open")
        self.assertTrue(
            frappe.db.exists(
                "Local Attendance Event",
                {
                    "local_session": session.name,
                    "teacher_id": replacement.teacher_id,
                    "event_type": "session_opened",
                },
            )
        )


class TestStudentSignatureP1E(FrappeTestCase):
    def test_provisional_checkin_is_converted_when_teacher_opens_session(self):
        teacher = _insert_teacher_with_pin()
        student = insert_student(uid("ETU-P1E"))
        session = insert_session(teacher_id=teacher.teacher_id)
        _add_roster(session, student)

        checkin = provisional_checkin(
            session.attendance_session_id,
            student.student_id,
            fingerprint=_fingerprint(),
            remote_addr="192.168.50.10",
        )
        self.assertTrue(checkin["ok"])
        self.assertEqual(checkin["status"], "pending_validation")

        clear_auth_rate_limit(teacher.teacher_id)
        opened = open_session(session.attendance_session_id, teacher.teacher_id, "123456")
        self.assertTrue(opened["ok"])
        self.assertEqual(opened["converted_provisional"], 1)
        self.assertTrue(
            frappe.db.exists(
                "Local Attendance Event",
                {
                    "local_session": session.name,
                    "student_id": student.student_id,
                    "event_type": "student_signature_validated",
                    "attendance_state": "Validated",
                },
            )
        )

    def test_provisional_checkin_hashes_long_browser_fingerprint(self):
        teacher = _insert_teacher_with_pin()
        student = insert_student(uid("ETU-P1E"))
        session = insert_session(teacher_id=teacher.teacher_id)
        _add_roster(session, student)
        fingerprint = _fingerprint()
        fingerprint["fingerprint"] = "Mozilla/5.0 " + ("very-long-browser-fingerprint|" * 12)

        checkin = provisional_checkin(
            session.attendance_session_id,
            student.student_id,
            fingerprint=fingerprint,
            remote_addr="192.168.50.10",
        )

        self.assertTrue(checkin["ok"])
        stored = frappe.db.get_value(
            "Local Device Fingerprint",
            {"event_id": checkin["event_id"]},
            "fingerprint",
        )
        self.assertTrue(stored.startswith("sha256:"))
        self.assertLessEqual(len(stored), 140)

    def test_qr_signature_validates_roster_leave_and_anti_replay(self):
        teacher = _insert_teacher_with_pin()
        student = insert_student(uid("ETU-P1E"))
        leave_student = insert_student(uid("ETU-P1E"))
        session = insert_session(teacher_id=teacher.teacher_id)
        _add_roster(session, student)
        _add_roster(session, leave_student)
        frappe.get_doc(
            {
                "doctype": "Local Leave",
                "leave_id": uid("LEAVE-P1E"),
                "student_id": leave_student.student_id,
                "starts_at": session.planned_start,
                "ends_at": session.planned_end,
            }
        ).insert(ignore_permissions=True)

        clear_auth_rate_limit(teacher.teacher_id)
        self.assertTrue(open_session(session.attendance_session_id, teacher.teacher_id, "123456")["ok"])
        payload_json = get_qr_frame(session.attendance_session_id)["payload_json"]

        signed = submit_qr_signature(
            student.student_id,
            payload_json,
            fingerprint=_fingerprint(),
            remote_addr="192.168.50.10",
        )
        self.assertTrue(signed["ok"])
        self.assertEqual(signed["status"], "validated")

        duplicate = submit_qr_signature(student.student_id, payload_json, remote_addr="192.168.50.10")
        self.assertFalse(duplicate["ok"])
        self.assertEqual(duplicate["status"], "already_signed")

        leave = submit_qr_signature(leave_student.student_id, payload_json, remote_addr="192.168.50.10")
        self.assertFalse(leave["ok"])
        self.assertEqual(leave["status"], "student_on_leave")

    def test_signature_after_closure_is_refused_and_secret_is_purged_after_grace_period(self):
        teacher = _insert_teacher_with_pin()
        student = insert_student(uid("ETU-P1E"))
        now = now_datetime()
        session = insert_session(
            teacher_id=teacher.teacher_id,
            planned_start=add_to_date(now, hours=-2, as_datetime=True),
            planned_end=add_to_date(now, hours=-1, as_datetime=True),
            session_date=now.date(),
            status="Open",
            secret_session="a" * 64,
            secret_generated_at=add_to_date(now, hours=-2, as_datetime=True),
        )
        _add_roster(session, student)

        closed = close_due_sessions(reference_time=now)
        self.assertEqual(closed["count"], 1)
        session.reload()
        self.assertEqual(session.status, "Closed")
        self.assertTrue(session.secret_purge_after)
        self.assertTrue(
            frappe.db.exists(
                "Local Attendance Event",
                {"local_session": session.name, "event_type": "session_auto_closed"},
            )
        )

        refused = provisional_checkin(session.attendance_session_id, student.student_id, remote_addr="192.168.50.10")
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["status"], "Session Already Closed")

        purged = purge_expired_session_secrets(reference_time=add_to_date(now, hours=2, as_datetime=True))
        self.assertEqual(purged["count"], 1)
        self.assertIsNone(get_decrypted_password("Local Session", session.name, "secret_session", raise_exception=False))
