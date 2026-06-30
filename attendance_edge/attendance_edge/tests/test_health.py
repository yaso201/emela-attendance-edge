from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from attendance_edge.api.health import ping


class TestAttendanceHealth(FrappeTestCase):
    def test_ping_returns_edge_identity(self):
        self.assertEqual(ping(), {"ok": True, "app": "attendance_edge"})
