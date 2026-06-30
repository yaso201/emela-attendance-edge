from __future__ import annotations

import frappe
from frappe import _


MIN_HASH_LENGTH = 40


def validate_hash_value(value: str | None, label: str) -> None:
    if not value:
        return
    if len(value) < MIN_HASH_LENGTH:
        frappe.throw(_("{0} must be a hash, not a clear value.").format(label))


def validate_select(value: str | None, allowed: set[str], label: str) -> None:
    if value and value not in allowed:
        frappe.throw(
            _("{0} has invalid value {1}. Allowed values: {2}.").format(
                label,
                frappe.bold(value),
                ", ".join(sorted(allowed)),
            )
        )


def ensure_new_document(doc, action: str = "modify") -> None:
    if not doc.is_new():
        frappe.throw(_("{0} is append-only and cannot be {1}.").format(doc.doctype, action))
