import frappe


@frappe.whitelist()
def ping():
    """Minimal P0 health endpoint for local site smoke checks."""
    return {"ok": True, "app": "attendance_edge"}
