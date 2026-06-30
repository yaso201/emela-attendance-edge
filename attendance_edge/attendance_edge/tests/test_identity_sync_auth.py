from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import passlibctx

from attendance_edge.identity_sync import sync_identity_payload
from attendance_edge.offline_auth import (
    authenticate_offline,
    clear_auth_rate_limit,
    verify_teacher_pin,
)
from attendance_edge.tests.helpers import uid


class TestIdentitySyncAndOfflineAuth(FrappeTestCase):
    def test_student_identity_sync_and_offline_password_auth(self):
        student_id = uid("ETU-P1C")
        user_id = f"{student_id.lower()}@example.test"
        payload = {
            "data": [
                {
                    "student_id": student_id,
                    "user_id": user_id,
                    "first_name": "Awa",
                    "last_name": "Houn",
                    "full_name": "Awa Houn",
                    "password_hash": passlibctx.hash("secret-pass"),
                    "groups": ["GRP-L1"],
                    "status": "Active",
                    "source_version": "2026-05-02 10:00:00",
                }
            ]
        }

        result = sync_identity_payload(payload, "students")
        self.assertEqual(result["created"], 1)

        auth = authenticate_offline(user_id, "secret-pass", actor_type="student")
        self.assertTrue(auth["ok"])
        self.assertEqual(auth["name"], student_id)

        clear_auth_rate_limit(user_id, actor_type="student")
        self.assertFalse(authenticate_offline(user_id, "bad", actor_type="student")["ok"])
        self.assertFalse(authenticate_offline(user_id, "bad", actor_type="student")["ok"])
        locked = authenticate_offline(user_id, "bad", actor_type="student")
        self.assertEqual(locked["status"], "locked")

    def test_teacher_identity_sync_and_pin_verification(self):
        teacher_id = uid("ENS-P1C")
        user_id = f"{teacher_id.lower()}@example.test"
        payload = {
            "data": [
                {
                    "teacher_id": teacher_id,
                    "user_id": user_id,
                    "full_name": "Jean Hounsa",
                    "password_hash": passlibctx.hash("teacher-pass"),
                    "pin_hash": passlibctx.hash("123456"),
                    "status": "Active",
                    "permissions": {"can_open_session": True},
                    "authorized_sessions": [],
                    "source_version": "2026-05-02 10:00:00",
                }
            ]
        }

        result = sync_identity_payload(payload, "teachers")
        self.assertEqual(result["created"], 1)

        auth = authenticate_offline(user_id, "teacher-pass", actor_type="teacher")
        self.assertTrue(auth["ok"])

        clear_auth_rate_limit(teacher_id)
        pin = verify_teacher_pin(teacher_id, "123456")
        self.assertTrue(pin["ok"])

        self.assertFalse(verify_teacher_pin(teacher_id, "000000")["ok"])
        self.assertFalse(verify_teacher_pin(teacher_id, "000000")["ok"])
        locked = verify_teacher_pin(teacher_id, "000000")
        self.assertEqual(locked["status"], "locked")

    def test_identity_sync_skips_new_user_without_password_hash(self):
        student_id = uid("ETU-P1C")
        payload = {
            "data": [
                {
                    "student_id": student_id,
                    "user_id": f"{student_id.lower()}@example.test",
                    "status": "Disabled",
                }
            ]
        }

        result = sync_identity_payload(payload, "students")

        self.assertEqual(result["skipped"], 1)
        self.assertFalse(frappe.db.exists("Local User Student", student_id))
