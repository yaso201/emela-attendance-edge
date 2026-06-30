from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from attendance_edge.validators import validate_select


SYNC_STATUSES = {"Pending", "Sent", "Acknowledged", "Failed"}


class LocalSyncQueue(Document):
    def validate(self):
        validate_select(self.status, SYNC_STATUSES, "Status")
        if (self.attempt_count or 0) < 0:
            frappe.throw(_("Attempt count cannot be negative."))
