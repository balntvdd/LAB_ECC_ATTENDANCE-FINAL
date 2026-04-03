from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import views as api_views
from .models import Attendance, Session, Student
from .utils import generate_keys, sign_message


User = get_user_model()


class AttendancePortalTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff_user = User.objects.create_user(
            username="teacher1",
            password="strong-pass-123",
            is_staff=True,
        )
        self.regular_user = User.objects.create_user(
            username="studentuser",
            password="strong-pass-123",
            is_staff=False,
        )

    def test_student_registration_is_one_time_only(self):
        payload = {
            "student_id": "20260001",
            "name": "Juan Dela Cruz",
            "section": "WMD-1A",
        }
        first_response = self.client.post(reverse("register-student"), payload, format="json")
        second_response = self.client.post(reverse("register-student"), payload, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(Student.objects.count(), 1)

    def test_only_staff_can_create_session(self):
        payload = {
            "section": "WMD-1A",
            "subject": "Networks",
            "time_in_start": "08:00",
            "time_in_end": "08:15",
            "time_out_start": "09:00",
        }

        self.client.force_authenticate(user=self.regular_user)
        forbidden = self.client.post(reverse("start-session"), payload, format="json")
        self.client.force_authenticate(user=self.staff_user)
        allowed = self.client.post(reverse("start-session"), payload, format="json")

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(Session.objects.count(), 1)
        self.assertTrue(Session.objects.first().session_code.startswith("ECC-"))

    def test_late_qr_scan_is_recorded_as_late(self):
        private_key, public_key = generate_keys()
        student = Student.objects.create(
            student_id="20260002",
            name="Maria Santos",
            section="WMD-1A",
            public_key=public_key,
        )

        now = timezone.localtime()
        session = Session.objects.create(
            section="WMD-1A",
            subject="Lab",
            time_in_start=(now - timedelta(minutes=20)).time().replace(microsecond=0),
            time_in_end=(now - timedelta(minutes=5)).time().replace(microsecond=0),
            time_out_start=(now + timedelta(minutes=30)).time().replace(microsecond=0),
            created_by=self.staff_user,
        )

        timestamp = timezone.now().isoformat()
        message = f"{student.student_id}|{student.section}|{session.session_code}|{timestamp}"
        raw_payload = f"{message}|{sign_message(private_key, message)}"

        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(
            reverse("verify-attendance"),
            {"raw": raw_payload, "session_code": session.session_code},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        attendance = Attendance.objects.get(student=student, session=session)
        self.assertEqual(attendance.status, "LATE")

    def test_report_export_csv_accepts_existing_format_query_param(self):
        Session.objects.create(
            section="WMD-1A",
            subject="Networks",
            time_in_start="08:00",
            time_in_end="08:15",
            time_out_start="09:00",
            created_by=self.staff_user,
        )
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("export-attendance-report"), {"format": "csv"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn('attachment; filename="attendance-report.csv"', response["Content-Disposition"])

    def test_report_export_pdf_accepts_existing_format_query_param(self):
        if api_views.canvas is None:
            self.skipTest("reportlab is not installed")

        Session.objects.create(
            section="WMD-1A",
            subject="Networks",
            time_in_start="08:00",
            time_in_end="08:15",
            time_out_start="09:00",
            created_by=self.staff_user,
        )
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("export-attendance-report"), {"format": "pdf"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="attendance-report.pdf"', response["Content-Disposition"])

    def test_staff_can_list_registered_students_with_derived_fields(self):
        Student.objects.create(
            student_id="20260003",
            name="Ana Reyes",
            section="BSIT-3A",
            public_key="public-key",
        )
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("list-students"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["students"][0]["course"], "BSIT")
        self.assertEqual(response.data["students"][0]["year_level"], "3rd Year")
        self.assertEqual(response.data["students"][0]["status"], "Registered")