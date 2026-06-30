from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LocalSessionRoster(Document):
    def validate(self):
        if frappe.db.exists(
            "Local Session Roster",
            {
                "local_session": self.local_session,
                "student_id": self.student_id,
                "name": ("!=", self.name),
            },
        ):
            frappe.throw(_("Student already exists in this local session roster."))
