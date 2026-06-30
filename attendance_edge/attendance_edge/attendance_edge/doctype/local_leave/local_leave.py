from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LocalLeave(Document):
    def validate(self):
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            frappe.throw(_("Leave end must be after leave start."))
