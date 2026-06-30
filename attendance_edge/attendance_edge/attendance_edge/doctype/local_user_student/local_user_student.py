from __future__ import annotations

from frappe.model.document import Document

from attendance_edge.validators import validate_hash_value


class LocalUserStudent(Document):
    def validate(self):
        validate_hash_value(self.password_hash, "Password hash")
