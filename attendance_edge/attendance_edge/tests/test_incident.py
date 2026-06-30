from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime


class TestLocalIncident(FrappeTestCase):
    def test_incident_accepts_critical_severity(self):
        incident = frappe.get_doc(
            {
                "doctype": "Local Incident",
                "incident_type": "Sync",
                "severity": "Critical",
                "detected_at": now_datetime(),
                "description": "Central API unavailable",
            }
        ).insert(ignore_permissions=True)

        self.assertEqual(incident.severity, "Critical")

    def test_incident_rejects_unknown_severity(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Local Incident",
                    "incident_type": "Sync",
                    "severity": "Blocker",
                    "detected_at": now_datetime(),
                    "description": "Invalid severity",
                }
            ).insert(ignore_permissions=True)
