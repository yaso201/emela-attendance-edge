from __future__ import annotations

from frappe.model.document import Document

from attendance_edge.validators import validate_select


SEVERITIES = {"Low", "Medium", "High", "Critical"}


class LocalIncident(Document):
    def validate(self):
        validate_select(self.severity, SEVERITIES, "Severity")
