from django.urls import path

from .views import (
    api_login,
    api_logout,
    export_attendance_report,
    generate_qr,
    list_sessions,
    list_students,
    portal_bootstrap,
    debug_request,
    register_student,
    session_dashboard,
    session_report,
    start_session,
    verify_attendance,
)

urlpatterns = [
    path("login/", api_login, name="api-login"),
    path("logout/", api_logout, name="api-logout"),
    path("register/", register_student, name="register-student"),
    path("generate-qr/", generate_qr, name="generate-qr"),
    path("start-session/", start_session, name="start-session"),
    path("verify-attendance/", verify_attendance, name="verify-attendance"),
    path("sessions/", list_sessions, name="list-sessions"),
    path("students/", list_students, name="list-students"),
    path("dashboard/", session_dashboard, name="session-dashboard"),
    path("portal-bootstrap/", portal_bootstrap, name="portal-bootstrap"),
    path("debug-request/", debug_request, name="debug-request"),
    path("reports/export/", export_attendance_report, name="export-attendance-report"),
    path("session-report/<str:session_code>/", session_report, name="session-report"),
]