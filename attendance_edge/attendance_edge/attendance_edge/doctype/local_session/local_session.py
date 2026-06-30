from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from attendance_edge.validators import validate_select


SESSION_STATUSES = {"Pending", "Open", "Closed", "SessionCancelled", "Incident"}


class LocalSession(Document):
    def validate(self):
        validate_select(self.status, SESSION_STATUSES, "Status")
        if self.planned_start and self.planned_end and self.planned_end <= self.planned_start:
            frappe.throw(_("Planned end must be after planned start."))
