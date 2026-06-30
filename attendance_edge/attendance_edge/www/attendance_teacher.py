import frappe


def get_context(context):
    context.no_cache = 1
    context.title = "Attendance enseignant"
    context.body_class = "attendance-ui attendance-teacher-page"
    context.csrf_token = frappe.sessions.get_csrf_token()
