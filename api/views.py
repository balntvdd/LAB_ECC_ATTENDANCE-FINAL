import base64
import csv
import io
import json
import re
from urllib.parse import unquote

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt #add

from .models import Attendance, SECTION_CHOICES, Session, Student
from .utils import generate_keys, sign_message, verify_signature

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
except Exception:
    letter = None
    inch = None
    canvas = None


class IsStaffUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


def staff_required(view_func):
    return login_required(user_passes_test(lambda user: user.is_staff, login_url="/portal/login/")(view_func))


def serialize_session(session):
    return {
        "session_code": session.session_code,
        "section": session.section,
        "subject": session.subject or "General Session",
        "date": session.date.isoformat(),
        "status": session.status,
        "time_in_start": session.time_in_start.strftime("%H:%M"),
        "time_in_end": session.time_in_end.strftime("%H:%M"),
        "time_out_start": session.time_out_start.strftime("%H:%M"),
        "created_by": session.created_by.get_username() if session.created_by else "System",
    }


def get_filtered_sessions(request):
    sessions = Session.objects.all()
    section = request.GET.get("section")
    date = parse_date(request.GET.get("date") or "")

    if section:
        sessions = sessions.filter(section=section)
    if date:
        sessions = sessions.filter(date=date)
    return sessions


def build_session_summary(session):
    students = Student.objects.filter(section=session.section).order_by("student_id")
    attendance_map = {
        record.student_id: record
        for record in Attendance.objects.select_related("student").filter(session=session)
    }

    present = []
    late = []
    absent = []

    for student in students:
        record = attendance_map.get(student.id)
        if not record or not record.time_in:
            absent.append(student)
            continue
        item = {
            "student_id": student.student_id,
            "name": student.name,
            "section": student.section,
            "time_in": timezone.localtime(record.time_in).strftime("%Y-%m-%d %I:%M %p"),
            "time_out": timezone.localtime(record.time_out).strftime("%Y-%m-%d %I:%M %p") if record.time_out else "",
            "status": record.status,
        }
        if record.status == "LATE":
            late.append(item)
        else:
            present.append(item)

    absent_payload = [
        {
            "student_id": student.student_id,
            "name": student.name,
            "section": student.section,
        }
        for student in absent
    ]

    return {
        "session": serialize_session(session),
        "counts": {
            "present": len(present),
            "late": len(late),
            "absent": len(absent_payload),
            "total_students": students.count(),
        },
        "present": present,
        "late": late,
        "absent": absent_payload,
    }


def render_report_rows(summary):
    rows = []
    for key in ("present", "late", "absent"):
        entries = summary[key]
        if not entries:
            continue
        for entry in entries:
            rows.append(
                {
                    "session_code": summary["session"]["session_code"],
                    "date": summary["session"]["date"],
                    "section": entry["section"],
                    "student_id": entry["student_id"],
                    "name": entry["name"],
                    "status": key.upper(),
                    "time_in": entry.get("time_in", ""),
                    "time_out": entry.get("time_out", ""),
                }
            )
    return rows


def parse_section_details(section):
    match = re.match(r"^(?P<course>[A-Z]+)-(?P<year>\d)(?P<section>[A-Z])$", section or "")
    if not match:
        return {
            "course": section or "N/A",
            "year_level": "N/A",
            "section_label": section or "N/A",
        }

    year = int(match.group("year"))
    suffix = "th"
    if year == 1:
        suffix = "st"
    elif year == 2:
        suffix = "nd"
    elif year == 3:
        suffix = "rd"

    return {
        "course": match.group("course"),
        "year_level": f"{year}{suffix} Year",
        "section_label": f"{match.group('year')}{match.group('section')}",
    }


def serialize_student(student):
    section_details = parse_section_details(student.section)
    return {
        "student_id": student.student_id,
        "full_name": student.name,
        "course": section_details["course"],
        "year_level": section_details["year_level"],
        "section": student.section,
        "section_label": section_details["section_label"],
        "email": "",
        "date_registered": timezone.localtime(student.registered_at).strftime("%Y-%m-%d %I:%M %p"),
        "status": "Registered",
    }


def build_basic_pdf(lines, title="Attendance Report"):
    def escape_pdf_text(value):
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    page_width = 612
    page_height = 792
    margin = 40
    line_height = 14
    usable_height = page_height - (margin * 2)
    lines_per_page = max(1, int(usable_height // line_height))

    pages = []
    for start in range(0, len(lines), lines_per_page):
        pages.append(lines[start : start + lines_per_page])
    if not pages:
        pages = [[]]

    objects = []
    page_ids = []
    content_ids = []
    font_id = 3

    next_object_id = 4
    for _ in pages:
        page_ids.append(next_object_id)
        next_object_id += 1
        content_ids.append(next_object_id)
        next_object_id += 1

    objects.append((1, "<< /Type /Catalog /Pages 2 0 R >>"))
    objects.append((2, f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(page_ids)} >>"))
    objects.append((font_id, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    for page_id, content_id, page_lines in zip(page_ids, content_ids, pages):
        objects.append(
            (
                page_id,
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>",
            )
        )

        text_commands = ["BT", "/F1 12 Tf", f"1 0 0 1 {margin} {page_height - margin} Tm", f"({escape_pdf_text(title)}) Tj"]
        current_y_offset = line_height * 2
        for line in page_lines:
            safe_line = escape_pdf_text(line)
            text_commands.append(f"1 0 0 1 {margin} {page_height - margin - current_y_offset} Tm")
            text_commands.append(f"({safe_line}) Tj")
            current_y_offset += line_height
        text_commands.append("ET")
        stream = "\n".join(text_commands).encode("latin-1", errors="replace")
        objects.append((content_id, f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream"))

    pdf = io.BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = {}
    for object_id, body in objects:
        offsets[object_id] = pdf.tell()
        pdf.write(f"{object_id} 0 obj\n{body}\nendobj\n".encode("latin-1"))

    xref_offset = pdf.tell()
    max_object_id = max(object_id for object_id, _ in objects)
    pdf.write(f"xref\n0 {max_object_id + 1}\n".encode("latin-1"))
    pdf.write(b"0000000000 65535 f \n")
    for object_id in range(1, max_object_id + 1):
        pdf.write(f"{offsets[object_id]:010d} 00000 n \n".encode("latin-1"))
    pdf.write(
        (
            f"trailer\n<< /Size {max_object_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("latin-1")
    )
    return pdf.getvalue()


def portal_login_view(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("portal-dashboard")
    return render(request, "portal_login.html", {"sections": SECTION_CHOICES})


@staff_required
def portal_dashboard_view(request):
    return render(request, "portal_dashboard.html", {"sections": SECTION_CHOICES})


def student_portal_view(request):
    return render(request, "student.html", {"sections": SECTION_CHOICES})

@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def api_login(request):
    username = request.data.get("username", "").strip()
    password = request.data.get("password", "")

    user = authenticate(username=username, password=password)
    if user is None:
        return Response({"error": "Invalid credentials"}, status=400)
    if not user.is_staff:
        return Response({"error": "Admin or teacher access only"}, status=403)

    login(request, user)
    return Response(
        {
            "success": True,
            "user": {
                "username": user.get_username(),
                "is_superuser": user.is_superuser,
            },
        }
    )


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_logout(request):
    logout(request)
    return Response({"success": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def portal_bootstrap(request):
    # Provide explicit diagnostics for unauthenticated/unauthorized requests
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return Response(
            {
                "error": "Not authenticated",
                "detail": "Session cookie missing or not sent. Ensure frontend uses credentials: 'include' and that SameSite=None is set for cookies.",
            },
            status=401,
        )
    if not getattr(user, 'is_staff', False):
        return Response({"error": "Staff only", "detail": "User is not staff."}, status=403)
    sessions = list(Session.objects.all()[:12])
    active_session = Session.objects.filter(status="ACTIVE").first()
    session = active_session or (sessions[0] if sessions else None)

    payload = {
        "user": {
            "username": request.user.get_username(),
            "is_superuser": request.user.is_superuser,
        },
        "sections": [choice[0] for choice in SECTION_CHOICES],
        "sessions": [serialize_session(item) for item in sessions],
        "selected_session": build_session_summary(session) if session else None,
    }
    return Response(payload)


@api_view(["GET", "POST"]) 
@permission_classes([AllowAny])
def debug_request(request):
    # Return cookies and a subset of headers to help diagnose why cookies
    # are not being sent from the browser (SameSite, CORS, host mismatch).
    headers = {k: v for k, v in request.META.items() if k.startswith("HTTP_")}
    try:
        session_items = dict(request.session.items())
    except Exception:
        session_items = {}
    return Response(
        {
            "cookies": request.COOKIES,
            "session": session_items,
            "headers": headers,
        }
    )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def register_student(request):
    student_id = str(request.data.get("student_id", "")).strip()
    name = request.data.get("name", "").strip()
    section = request.data.get("section")

    if not all([student_id, name, section]):
        return Response({"error": "Student ID, full name, and section are required"}, status=400)

    allowed_sections = [item[0] for item in SECTION_CHOICES]
    if section not in allowed_sections:
        return Response({"error": "Invalid section"}, status=400)

    if not re.match(r"^\d{1,10}$", student_id):
        return Response({"error": "Student ID must be numeric and up to 10 digits"}, status=400)

    if Student.objects.filter(student_id=student_id).exists():
        return Response({"error": "Student is already registered"}, status=400)

    if len(name) < 3 or re.search(r"\d", name):
        return Response({"error": "Enter a valid full name"}, status=400)
    if not re.match(r"^[A-Za-z .'\-]+$", name):
        return Response({"error": "Name contains unsupported characters"}, status=400)

    name_parts = [part for part in re.split(r"\s+", name) if part]
    if len(name_parts) < 2:
        return Response({"error": "Please enter full name"}, status=400)

    private_key, public_key = generate_keys()
    student = Student.objects.create(
        student_id=student_id,
        name=name,
        section=section,
        public_key=public_key,
    )

    return Response(
        {
            "message": "Registered successfully",
            "student": {
                "student_id": student.student_id,
                "name": student.name,
                "section": student.section,
            },
            "private_key": private_key,
            "private_key_hint": "Save this private key now. It cannot be recovered later.",
        }
    )


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsStaffUser])
def start_session(request):
    section = request.data.get("section")
    subject = (request.data.get("subject") or "").strip()
    time_in_start = request.data.get("time_in_start")
    time_in_end = request.data.get("time_in_end")
    time_out_start = request.data.get("time_out_start")

    if not all([section, time_in_start, time_in_end, time_out_start]):
        return Response({"error": "Section and session times are required"}, status=400)

    allowed_sections = [item[0] for item in SECTION_CHOICES]
    if section not in allowed_sections:
        return Response({"error": "Invalid section"}, status=400)

    parsed_time_in_start = parse_time(time_in_start)
    parsed_time_in_end = parse_time(time_in_end)
    parsed_time_out_start = parse_time(time_out_start)

    if not all([parsed_time_in_start, parsed_time_in_end, parsed_time_out_start]):
        return Response({"error": "Invalid time format"}, status=400)

    if not (parsed_time_in_start < parsed_time_in_end < parsed_time_out_start):
        return Response({"error": "Session time flow must be start < late threshold < time out"}, status=400)

    session = Session.objects.create(
        section=section,
        subject=subject,
        time_in_start=parsed_time_in_start,
        time_in_end=parsed_time_in_end,
        time_out_start=parsed_time_out_start,
        created_by=request.user,
    )

    return Response({"message": "Session created", "session": serialize_session(session)})


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsStaffUser])
def list_sessions(request):
    sessions = get_filtered_sessions(request)[:50]
    return Response({"sessions": [serialize_session(session) for session in sessions]})


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsStaffUser])
def list_students(request):
    section = (request.GET.get("section") or "").strip()
    query = (request.GET.get("q") or "").strip()

    students = Student.objects.all().order_by("-registered_at", "student_id")
    if section:
        students = students.filter(section=section)
    if query:
        students = students.filter(Q(student_id__icontains=query) | Q(name__icontains=query))

    students = list(students[:300])
    return Response(
        {
            "students": [serialize_student(student) for student in students],
            "total": len(students),
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsStaffUser])
def session_dashboard(request):
    session_code = request.GET.get("session_code")
    sessions = get_filtered_sessions(request)

    selected = None
    if session_code:
        selected = sessions.filter(session_code=session_code).first()
        if not selected:
            return Response({"error": "Session not found"}, status=404)
    else:
        selected = sessions.first()

    aggregate = Session.objects.values("section").annotate(total=Count("id")).order_by("section")
    summary = build_session_summary(selected) if selected else None

    return Response(
        {
            "sessions": [serialize_session(session) for session in sessions[:25]],
            "section_totals": list(aggregate),
            "selected_session": summary,
        }
    )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def generate_qr(request):
    student_id = str(request.data.get("student_id", "")).strip()
    private_key = request.data.get("private_key")
    session_code = str(request.data.get("session_code", "")).strip().upper()

    if not all([student_id, private_key, session_code]):
        return Response({"error": "Session code, student ID, and private key are required"}, status=400)

    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response({"error": "Student not found"}, status=404)

    session = Session.objects.filter(session_code=session_code, status="ACTIVE").first()
    if not session:
        return Response({"error": "Session not found or already closed"}, status=400)
    if student.section != session.section:
        return Response({"error": "Student section does not match the selected session"}, status=400)

    timestamp = timezone.now().isoformat()
    message = f"{student_id}|{student.section}|{session.session_code}|{timestamp}"

    try:
        signature = sign_message(private_key, message)
    except Exception:
        return Response({"error": "Invalid private key"}, status=400)

    raw_payload = f"{student_id}|{student.section}|{session.session_code}|{timestamp}|{signature}"
    return Response(
        {
            "student_id": student_id,
            "section": student.section,
            "session_code": session.session_code,
            "timestamp": timestamp,
            "signature": signature,
            "raw_payload": raw_payload,
        }
    )


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsStaffUser])
def verify_attendance(request):
    raw = request.data.get("raw")
    session_code_override = request.data.get("session_code")

    if not raw:
        return Response({"error": "No QR data provided"}, status=400)

    parts = raw.strip().split("|")
    if len(parts) < 5:
        return Response({"error": "Invalid QR format"}, status=400)

    student_id, section, session_code, timestamp = parts[:4]
    signature = unquote("|".join(parts[4:])).replace(" ", "+")

    if session_code_override and session_code != session_code_override:
        return Response({"error": "QR belongs to a different session"}, status=400)

    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response({"error": "Student not found"}, status=400)

    session = Session.objects.filter(session_code=session_code, status="ACTIVE").first()
    if not session:
        return Response({"error": "Invalid or closed session"}, status=400)
    if student.section != session.section:
        return Response({"error": "Section mismatch"}, status=400)

    qr_time = parse_datetime(timestamp)
    if not qr_time:
        return Response({"error": "Invalid timestamp"}, status=400)
    if qr_time.tzinfo is None:
        qr_time = timezone.make_aware(qr_time)

    now = timezone.localtime()
    if abs((now - qr_time).total_seconds()) > 10800:
        return Response({"error": "QR expired"}, status=400)

    message = f"{student_id}|{section}|{session_code}|{timestamp}"
    if not verify_signature(student.public_key, message, signature):
        return Response({"error": "Invalid signature"}, status=400)

    now_time = now.time()
    attendance = Attendance.objects.filter(student=student, session=session).first()

    if now_time < session.time_in_start:
        return Response({"error": "Session has not started yet"}, status=400)

    if now_time < session.time_out_start:
        if attendance:
            return Response({"error": "Student is already timed in for this session"}, status=400)

        status = "PRESENT" if now_time <= session.time_in_end else "LATE"
        attendance = Attendance.objects.create(
            student=student,
            session=session,
            time_in=now,
            status=status,
        )
        return Response(
            {
                "message": f"{status.title()} time-in recorded",
                "student": student.name,
                "student_id": student.student_id,
                "section": student.section,
                "session_code": session.session_code,
                "status": status,
                "time": attendance.time_in.isoformat(),
            }
        )

    if not attendance:
        return Response({"error": "No time-in record found for this session"}, status=400)
    if attendance.time_out:
        return Response({"error": "Student is already timed out"}, status=400)

    attendance.time_out = now
    attendance.save(update_fields=["time_out"])
    return Response(
        {
            "message": "Time-out recorded",
            "student": student.name,
            "student_id": student.student_id,
            "section": student.section,
            "session_code": session.session_code,
            "status": attendance.status,
            "time": attendance.time_out.isoformat(),
        }
    )


def export_attendance_report(request):
    if request.method != "GET":
        return JsonResponse({"detail": 'Method "%s" not allowed.' % request.method}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication credentials were not provided."}, status=403)
    if not request.user.is_staff:
        return JsonResponse({"detail": "You do not have permission to perform this action."}, status=403)

    session_code = request.GET.get("session_code")
    export_format = (request.GET.get("format") or "csv").lower()
    sessions = get_filtered_sessions(request)

    if session_code:
        sessions = sessions.filter(session_code=session_code)
    sessions = list(sessions[:50])
    if not sessions:
        return JsonResponse({"error": "No matching sessions found"}, status=404)

    summaries = [build_session_summary(session) for session in sessions]
    rows = []
    for summary in summaries:
        rows.extend(render_report_rows(summary))

    if export_format == "pdf":
        if canvas is not None:
            buffer = io.BytesIO()
            pdf = canvas.Canvas(buffer, pagesize=letter)
            width, height = letter
            margin = 0.55 * inch
            y = height - margin

            pdf.setFont("Helvetica-Bold", 16)
            pdf.drawString(margin, y, "Attendance Report")
            y -= 0.28 * inch
            pdf.setFont("Helvetica", 10)
            pdf.drawString(margin, y, f"Generated: {timezone.localtime().strftime('%Y-%m-%d %I:%M %p')}")
            y -= 0.24 * inch

            for summary in summaries:
                pdf.setFont("Helvetica-Bold", 12)
                session_title = f"{summary['session']['session_code']} | {summary['session']['section']} | {summary['session']['date']}"
                pdf.drawString(margin, y, session_title)
                y -= 0.2 * inch
                pdf.setFont("Helvetica", 10)

                for group in ("present", "late", "absent"):
                    entries = summary[group]
                    if not entries:
                        continue
                    pdf.drawString(margin + 8, y, group.title())
                    y -= 0.16 * inch
                    for entry in entries:
                        line = f"{entry['student_id']} | {entry['name']}"
                        if entry.get("time_in"):
                            line += f" | IN {entry['time_in']}"
                        if entry.get("time_out"):
                            line += f" | OUT {entry['time_out']}"
                        pdf.drawString(margin + 18, y, line[:110])
                        y -= 0.16 * inch
                        if y < margin + 40:
                            pdf.showPage()
                            y = height - margin
                            pdf.setFont("Helvetica", 10)
                    y -= 0.1 * inch

                if y < margin + 80:
                    pdf.showPage()
                    y = height - margin

            pdf.save()
            pdf_bytes = buffer.getvalue()
        else:
            pdf_lines = [f"Generated: {timezone.localtime().strftime('%Y-%m-%d %I:%M %p')}", ""]
            for summary in summaries:
                pdf_lines.append(
                    f"{summary['session']['session_code']} | {summary['session']['section']} | {summary['session']['date']}"
                )
                for group in ("present", "late", "absent"):
                    entries = summary[group]
                    if not entries:
                        continue
                    pdf_lines.append(f"  {group.title()}")
                    for entry in entries:
                        line = f"    {entry['student_id']} | {entry['name']}"
                        if entry.get("time_in"):
                            line += f" | IN {entry['time_in']}"
                        if entry.get("time_out"):
                            line += f" | OUT {entry['time_out']}"
                        pdf_lines.append(line[:110])
                pdf_lines.append("")
            pdf_bytes = build_basic_pdf(pdf_lines)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="attendance-report.pdf"'
        return response

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["session_code", "date", "section", "student_id", "name", "status", "time_in", "time_out"],
    )
    writer.writeheader()
    writer.writerows(rows)

    response = HttpResponse(output.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="attendance-report.csv"'
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsStaffUser])
def session_report(request, session_code):
    session = Session.objects.filter(session_code=session_code).first()
    if not session:
        return Response({"error": "Session not found"}, status=404)
    return Response(build_session_summary(session))