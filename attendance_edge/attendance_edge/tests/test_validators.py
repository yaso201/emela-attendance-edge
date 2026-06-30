from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from attendance_edge.validators import validate_hash_value, validate_select


class TestAttendanceValidators(FrappeTestCase):
    def test_hash_validator_allows_empty_for_optional_hashes(self):
        validate_hash_value(None, "PIN hash")
        validate_hash_value("", "PIN hash")

    def test_hash_validator_rejects_clear_value(self):
        with self.assertRaises(frappe.ValidationError):
            validate_hash_value("123456", "PIN hash")

    def test_select_validator_rejects_unknown_value(self):
        with self.assertRaises(frappe.ValidationError):
            validate_select("Unknown", {"Pending", "Synced"}, "Sync Status")
