from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from attendance_edge.tests.helpers import uid


class TestLocalDeviceFingerprint(FrappeTestCase):
    def test_fingerprint_requires_fingerprint_value(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local Device Fingerprint",
                    "student_id": uid("ETU"),
                    "event_id": uid("EVT"),
                    "captured_at": now_datetime(),
                }
            ).insert(ignore_permissions=True)

    def test_fingerprint_captures_network_and_device_context(self):
        doc = frappe.get_doc(
            {
                "doctype": "Local Device Fingerprint",
                "student_id": uid("ETU"),
                "event_id": uid("EVT"),
                "fingerprint": uid("FP"),
                "user_agent": "pytest",
                "local_ip": "192.168.50.10",
                "screen_resolution": "390x844",
                "timezone": "Africa/Porto-Novo",
                "captured_at": now_datetime(),
            }
        ).insert(ignore_permissions=True)

        self.assertEqual(doc.local_ip, "192.168.50.10")
        self.assertEqual(doc.timezone, "Africa/Porto-Novo")
