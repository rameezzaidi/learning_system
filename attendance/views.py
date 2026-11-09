import csv
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.rbac import has_perm, perm_required
from core import audit, scope
from core.notify import notify

from . import services
from .models import AttendanceRecord, LeaveRequest, StaffAttendance


def _day(request):
    try:
        d = date.fromisoformat(request.GET.get("date") or request.POST.get("date") or "")
    except ValueError:
        d = timezone.localdate()
    return min(d, timezone.localdate())


def can_view_student(user, student):
    if user.is_super_admin or user.pk == student.pk:
        return True
    if user.is_parent:
        return user.children.filter(pk=student.pk).exists()
    if user.is_management and has_perm(user, "attendance.view"):
        return scope.can_see_student(user, student)
    if user.is_teacher:
        from academics.models import Course, student_class
        cls = student_class(student)
        return bool(cls) and Course.objects.filter(teacher=user, school_class=cls).exists()
    return False


def _csv_safe(v):
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v


# ------------------------------------------------------------------ marking
@login_required
def index(request):
    classes = list(services.classes_for(request.user).select_related("campus"))
    if not classes and not (request.user.is_super_admin or request.user.is_management):
        raise PermissionDenied
    today = timezone.localdate()
    done = set(AttendanceRecord.objects.filter(school_class__in=classes, date=today).values_list("school_class_id", flat=True))
    return render(request, "attendance/index.html", {"rows": [(c, c.pk in done, services.class_students(c).count()) for c in classes], "today": today, "page": "attendance"})


@login_required
def mark(request, pk):
    from academics.models import SchoolClass
    cls = get_object_or_404(SchoolClass, pk=pk)
    if not services.can_mark(request.user, cls):
        raise PermissionDenied
    day = _day(request)
    if request.method == "POST":
        data = {}
        for s in services.class_students(cls):
            st = request.POST.get(f"s{s.pk}", "present")
            data[s.pk] = (st, request.POST.get(f"n{s.pk}", ""))
        counts = services.save_sheet(cls, day, data, request.user)
        audit.record(request, "attendance.mark", f"{cls} {day}", ", ".join(f"{k}={v}" for k, v in counts.items()))
        messages.success(request, f"Attendance saved for {day:%d %b %Y}: " + ", ".join(f"{v} {k}" for k, v in counts.items()) + ".")
        return redirect(f"/attendance/class/{cls.pk}/?date={day.isoformat()}")
    rows, saved = services.sheet(cls, day)
    from timetable.services import holiday_on
    hol = holiday_on(day, cls.campus_id)
    return render(request, "attendance/mark.html", {"holiday": hol, "weekend": day.weekday() == 6, "cls": cls, "rows": rows, "day": day, "saved": saved, "today": timezone.localdate(),
                                                   "prev": day - timedelta(days=1), "next": day + timedelta(days=1), "statuses": [("present", "Present"), ("absent", "Absent"), ("late", "Late"), ("leave", "Leave")], "page": "attendance"})


# ------------------------------------------------------------------ student view
@login_required
def student(request, pk):
    st = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    if not can_view_student(request.user, st):
        raise PermissionDenied
    start, end = services.parse_range(request, 60)
    recs = AttendanceRecord.objects.filter(student=st, date__range=(start, end))
    return render(request, "attendance/student.html", {
        "student": st, "s": services.summary(st, start, end), "recs": recs, "start": start, "end": end,
        "leaves": st.leave_requests.all()[:10], "can_request": request.user.pk == st.pk or (request.user.is_parent and request.user.children.filter(pk=st.pk).exists()),
        "kids": list(request.user.children.all()) if request.user.is_parent else [], "page": "attendance", "active_child": st.pk})


@login_required
def my(request):
    u = request.user
    if u.is_student:
        return redirect("attendance:student", pk=u.pk)
    if u.is_parent and u.children.exists():
        return redirect("attendance:student", pk=u.children.first().pk)
    raise PermissionDenied


# ------------------------------------------------------------------ leave
@login_required
@require_POST
def leave_request(request, pk):
    st = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    me = request.user
    if not (me.pk == st.pk or (me.is_parent and me.children.filter(pk=st.pk).exists())):
        raise PermissionDenied
    try:
        f, t = date.fromisoformat(request.POST.get("from_date", "")), date.fromisoformat(request.POST.get("to_date", ""))
    except ValueError:
        messages.error(request, "Choose valid dates.")
        return redirect("attendance:student", pk=st.pk)
    reason = request.POST.get("reason", "").strip()
    if t < f or not reason or (t - f).days > 60:
        messages.error(request, "Check the dates (end after start, up to 60 days) and give a reason.")
        return redirect("attendance:student", pk=st.pk)
    lr = LeaveRequest.objects.create(student=st, from_date=f, to_date=t, reason=reason[:300], requested_by=me)
    from academics.models import Course, student_class
    cls = student_class(st)
    teachers = {c.teacher for c in Course.objects.filter(school_class=cls, teacher__isnull=False).select_related("teacher")} if cls else set()
    for tch in teachers:
        notify(tch, f"Leave request: {st.display_name}", f"{f:%d %b} to {t:%d %b}: {reason[:120]}", "/attendance/leaves/", "attendance")
    audit.record(request, "leave.request", st.username, f"{f} to {t}")
    messages.success(request, "Leave request sent to the class teachers.")
    return redirect("attendance:student", pk=st.pk)


def _leave_qs(user):
    qs = LeaveRequest.objects.select_related("student__student_profile__campus", "requested_by")
    if user.is_super_admin:
        return qs
    if user.is_teacher and has_perm(user, "attendance.leave_decide"):
        return qs.filter(student__enrollment__school_class__courses__teacher=user).distinct()
    if user.is_management and has_perm(user, "attendance.leave_decide"):
        ids = scope.campus_ids(user)
        return qs if ids is None else qs.filter(student__student_profile__campus_id__in=ids)
    return qs.none()


@login_required
def leaves(request):
    if not (request.user.is_super_admin or request.user.is_teacher or request.user.is_management):
        raise PermissionDenied
    status = request.GET.get("status", "pending")
    qs = _leave_qs(request.user)
    if status in dict(LeaveRequest.Status.choices):
        qs = qs.filter(status=status)
    return render(request, "attendance/leaves.html", {"rows": qs[:200], "status": status, "statuses": LeaveRequest.Status.choices, "page": "leaves"})


@login_required
@require_POST
def leave_decide(request, pk):
    lr = get_object_or_404(_leave_qs(request.user), pk=pk, status="pending")
    decision = request.POST.get("decision")
    if decision not in ("approved", "rejected"):
        raise PermissionDenied
    lr.status, lr.decided_by, lr.decided_at, lr.decision_note = decision, request.user, timezone.now(), request.POST.get("note", "")[:200]
    lr.save()
    audit.record(request, f"leave.{decision}", lr.student.username, f"{lr.from_date} to {lr.to_date}")
    from core.notify import notify_family
    notify_family(lr.student, f"Leave {decision}", f"{lr.from_date:%d %b} to {lr.to_date:%d %b}. {lr.decision_note}", "/attendance/me/", f"/attendance/student/{lr.student_id}/", "attendance")
    messages.success(request, f"Leave {decision}.")
    return redirect("attendance:leaves")


# ------------------------------------------------------------------ reports & staff
@login_required
@perm_required("attendance.view")
def report(request):
    start, end = services.parse_range(request, 30)
    classes = services.viewable_classes(request.user)
    rows = services.class_report(classes, start, end)
    low = []
    for r in rows:
        ids = list(services.class_students(r["cls"]).values_list("pk", flat=True))
        for sid, p in services.bulk_pct(ids, start, end).items():
            if p is not None and p < services.LOW_ATTENDANCE:
                low.append((User.objects.get(pk=sid), p, r["cls"]))
    low.sort(key=lambda t: t[1])
    if request.GET.get("format") == "csv":
        audit.record(request, "export.attendance", "report", f"{start} to {end}")
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="attendance.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Student", "Class", "Attendance %"])
        for u, p, c in low:
            w.writerow([_csv_safe(u.display_name), str(c), p])
        return resp
    return render(request, "attendance/report.html", {"rows": rows, "low": low[:100], "start": start, "end": end, "threshold": services.LOW_ATTENDANCE, "page": "att_report"})


@login_required
def staff(request):
    me = request.user
    if not (me.is_super_admin or (me.is_management and has_perm(me, "attendance.mark"))):
        raise PermissionDenied
    day = _day(request)
    teachers = list(services.teachers_for(me))
    if request.method == "POST":
        n = 0
        for t in teachers:
            st = request.POST.get(f"t{t.pk}")
            if st in services.STATUSES:
                StaffAttendance.objects.update_or_create(teacher=t, date=day, defaults={"status": st, "marked_by": me})
                n += 1
        audit.record(request, "attendance.staff", str(day), f"{n} teachers")
        messages.success(request, f"Teacher attendance saved for {day:%d %b %Y}.")
        return redirect(f"/attendance/staff/?date={day.isoformat()}")
    start = day - timedelta(days=30)
    rows = services.staff_sheet(day, teachers)
    for r in rows:
        c = {x["status"]: x["n"] for x in StaffAttendance.objects.filter(teacher=r["teacher"], date__range=(start, day)).values("status").annotate(n=Count("id"))}
        base = c.get("present", 0) + c.get("late", 0) + c.get("absent", 0)
        r["pct"] = round((c.get("present", 0) + c.get("late", 0)) * 100 / base) if base else None
    return render(request, "attendance/staff.html", {"rows": rows, "day": day, "statuses": [("present", "Present"), ("absent", "Absent"), ("late", "Late"), ("leave", "Leave")], "page": "att_staff"})
