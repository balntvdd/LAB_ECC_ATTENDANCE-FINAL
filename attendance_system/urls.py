from django.contrib import admin
from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie

from api.views import (
    export_attendance_report,
    portal_dashboard_view,
    portal_login_view,
    student_portal_view,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/reports/export/", export_attendance_report, name="export-attendance-report-direct"),
    path("api/reports/export", export_attendance_report, name="export-attendance-report-direct-no-slash"),
    path("api/", include("api.urls")),
    path("", ensure_csrf_cookie(student_portal_view), name="student-home"),
    path("student/", ensure_csrf_cookie(student_portal_view), name="student"),
    path("portal/login/", ensure_csrf_cookie(portal_login_view), name="portal-login"),
    path("portal/", ensure_csrf_cookie(portal_dashboard_view), name="portal-dashboard"),
]
