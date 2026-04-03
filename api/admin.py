from django.contrib import admin

from .models import Attendance, Session, Student


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_code",
        "section",
        "subject",
        "date",
        "time_in_start",
        "time_in_end",
        "time_out_start",
        "status",
        "created_by",
    )
    list_filter = ("status", "section", "date")
    search_fields = ("session_code", "subject", "created_by__username")
    readonly_fields = ("session_code", "start_time", "date", "created_by")

    fieldsets = (
        (
            "Session Details",
            {
                "fields": ("session_code", "section", "subject", "status", "created_by", "date", "start_time"),
            },
        ),
        (
            "Attendance Windows",
            {
                "fields": ("time_in_start", "time_in_end", "time_out_start"),
                "description": "Time-in end acts as the late threshold.",
            },
        ),
    )


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("student_id", "name", "section", "registered_at")
    list_filter = ("section",)
    search_fields = ("student_id", "name")
    readonly_fields = ("registered_at",)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("student", "session", "status", "time_in", "time_out")
    list_filter = ("status", "session__section", "session__date")
    search_fields = ("student__student_id", "student__name", "session__session_code")