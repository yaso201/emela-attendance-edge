from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LocalDeviceFingerprint(Document):
    def validate(self):
        if not self.fingerprint:
            frappe.throw(_("Fingerprint is required."))
