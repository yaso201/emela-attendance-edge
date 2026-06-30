from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from attendance_edge.validators import ensure_new_document, validate_select


EVENT_TYPES = {
    "session_opened",
    "session_closed",
    "session_auto_closed",
    "session_auto_closed_post_restart",
    "student_signature_received",
    "student_signature_validated",
    "student_signature_rejected",
    "student_provisional_checkin",
    "teacher_manual_mark",
    "leave_applied",
    "paper_mode_used",
    "incident_detected",
}


class LocalAttendanceEvent(Document):
    def validate(self):
        ensure_new_document(self)
        validate_select(self.event_type, EVENT_TYPES, "Event Type")

    def on_trash(self):
        frappe.throw(_("Local Attendance Event is append-only and cannot be deleted."))
