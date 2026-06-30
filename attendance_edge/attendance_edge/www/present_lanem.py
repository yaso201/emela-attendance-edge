import frappe


def get_context(context):
    context.no_cache = 1
    context.title = "present-lanem"
    context.body_class = "attendance-ui present-lanem-page"
    context.csrf_token = frappe.sessions.get_csrf_token()
