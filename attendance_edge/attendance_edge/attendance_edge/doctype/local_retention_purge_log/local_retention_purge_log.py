from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LocalRetentionPurgeLog(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw(_("Local Retention Purge Log is append-only and cannot be modified."))
        if not self.purge_run_id:
            frappe.throw(_("Purge run ID is required."))
        if not self.target_doctype:
            frappe.throw(_("Target DocType is required."))

    def on_trash(self):
        frappe.throw(_("Local Retention Purge Log is append-only and cannot be deleted."))
