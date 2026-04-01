import secrets
import string

from django.conf import settings
from django.db import models
from django.utils import timezone


SECTION_CHOICES = [
    ("WMD-1A", "WMD-1A"),
    ("WMD-1B", "WMD-1B"),
    ("WMD-1C", "WMD-1C"),
    ("WMD-2A", "WMD-2A"),
    ("WMD-2B", "WMD-2B"),
    ("WMD-2C", "WMD-2C"),
    ("BSIT-3A", "BSIT-3A"),
    ("BSIT-3B", "BSIT-3B"),
    ("BSIT-4A", "BSIT-4A"),
    ("BSIT-4B", "BSIT-4B"),
]


def generate_session_code():
    alphabet = string.ascii_uppercase + string.digits
    return "ECC-" + "".join(secrets.choice(alphabet) for _ in range(8))


class Student(models.Model):
    student_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    section = models.CharField(max_length=10, choices=SECTION_CHOICES)
    public_key = models.TextField()
    registered_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("student_id",)

    def __str__(self):
        return f"{self.student_id} - {self.name}"


class Session(models.Model):
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("CLOSED", "Closed"),
    ]

    session_code = models.CharField(max_length=32, unique=True, editable=False)
    section = models.CharField(max_length=10, choices=SECTION_CHOICES)
    subject = models.CharField(max_length=100, blank=True, null=True)
    date = models.DateField(auto_now_add=True)
    time_in_start = models.TimeField()
    time_in_end = models.TimeField(help_text="Late threshold")
    time_out_start = models.TimeField(verbose_name="Time out")
    start_time = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="ACTIVE")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_sessions",
    )

    class Meta:
        ordering = ("-date", "-start_time")

    def save(self, *args, **kwargs):
        if not self.session_code:
            while True:
                session_code = generate_session_code()
                if not Session.objects.filter(session_code=session_code).exists():
                    self.session_code = session_code
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.section} - {self.session_code}"


class Attendance(models.Model):
    STATUS_CHOICES = [
        ("PRESENT", "Present"),
        ("LATE", "Late"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="attendance_records")
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="attendance_records")
    time_in = models.DateTimeField(null=True, blank=True)
    time_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PRESENT")

    class Meta:
        ordering = ("student__student_id",)
        constraints = [
            models.UniqueConstraint(fields=("student", "session"), name="unique_attendance_per_session"),
        ]

    def __str__(self):
        return f"{self.student.student_id} - {self.session.session_code}"
