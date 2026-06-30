"""attendance_edge hooks.

P0 skeleton for the local Frappe edge site described by D5 DEC-ATT-04.
P1 will add local DocTypes, schedulers, sync services, and the student/teacher
local web surfaces.
"""

app_name = "attendance_edge"
app_title = "Attendance Edge"
app_publisher = "SI LaNEM"
app_description = "Local attendance capture for LaNEM classrooms"
app_email = "devnull@lanem.local"
app_license = "mit"

required_apps = ["frappe"]

website_route_rules = [
    {"from_route": "/attendance-teacher", "to_route": "attendance_teacher"},
    {"from_route": "/present-lanem", "to_route": "present_lanem"},
    {"from_route": "/present-lanem-sw.js", "to_route": "present_lanem_sw.js"},
]

scheduler_events = {
    "cron": {
        "* * * * *": [
            "attendance_edge.scheduler.run_closure_tick",
        ],
        "*/5 * * * *": [
            "attendance_edge.scheduler.run_opportunistic_sync",
        ],
        "0 4 1 * *": [
            "attendance_edge.compliance.run_monthly_local_retention_purge",
        ],
    },
    "daily": [
        "attendance_edge.scheduler.run_daily_planning_preload",
    ],
    "hourly": [
        "attendance_edge.scheduler.monitor_sync_queue",
    ],
}
