from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime, now_datetime

from attendance_edge.tests.helpers import insert_session, uid


class TestLocalSession(FrappeTestCase):
    def test_session_can_open_and_close_with_timestamps(self):
        session = insert_session()
        session.status = "Open"
        session.opened_at = now_datetime()
        session.save(ignore_permissions=True)

        loaded = frappe.get_doc("Local Session", session.name)
        self.assertEqual(loaded.status, "Open")
        self.assertTrue(loaded.opened_at)

        loaded.status = "Closed"
        loaded.closed_at = now_datetime()
        loaded.save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value("Local Session", session.name, "status"), "Closed")

    def test_session_rejects_unknown_status(self):
        with self.assertRaises(frappe.ValidationError):
            insert_session(status="Started")

    def test_session_rejects_end_before_start(self):
        with self.assertRaises(frappe.ValidationError):
            insert_session(
                attendance_session_id=uid("LSESS"),
                planned_start=get_datetime("2026-05-04 10:00:00"),
                planned_end=get_datetime("2026-05-04 08:00:00"),
            )
