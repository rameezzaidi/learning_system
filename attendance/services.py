from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import User
from accounts.rbac import has_perm
from core import scope
from core.notify import notify_family

from .models import AttendanceRecord, LeaveRequest, StaffAttendance

STATUSES = ("present", "absent", "late", "leave")
LOW_ATTENDANCE = 75.0


def class_students(school_class):
    return User.objects.filter(role=User.Role.STUDENT, is_active=True, enrollment__school_class=school_class).order_by("first_name", "username")


def classes_for(user):
    """Classes whose attendance this user may mark."""
    from academics.models import SchoolClass
    if user.is_super_admin:
        return SchoolClass.objects.all()
    if user.is_teacher and has_perm(user, "attendance.mark"):
        return SchoolClass.objects.filter(courses__teacher=user).distinct()
    if user.is_management and has_perm(user, "attendance.mark"):
        return scope.classes_for(user)
    return SchoolClass.objects.none()


def viewable_classes(user):
    """Classes whose attendance this user may read (reports)."""
    from academics.models import SchoolClass
    if user.is_super_admin:
        return SchoolClass.objects.all()
    if user.is_management and has_perm(user, "attendance.view"):
        return scope.classes_for(user)
    return classes_for(user)


def can_mark(user, school_class):
    return classes_for(user).filter(pk=school_class.pk).exists()


def approved_leave_ids(day, student_ids):
    return set(LeaveRequest.objects.filter(status="approved", from_date__lte=day, to_date__gte=day, student_id__in=student_ids)
               .values_list("student_id", flat=True))


def sheet(school_class, day):
    """Rows for the mark sheet: saved status, else 'leave' if approved leave covers the day, else blank (defaults to present in the UI)."""
    students = list(class_students(school_class))
    saved = {r.student_id: r for r in AttendanceRecord.objects.filter(school_class=school_class, date=day)}
    leave = approved_leave_ids(day, [s.id for s in students])
    rows = []
    for s in students:
        r = saved.get(s.id)
        rows.append({"student": s, "status": r.status if r else ("leave" if s.id in leave else ""), "note": r.note if r else "",
                     "saved": bool(r), "on_leave": s.id in leave})
    return rows, bool(saved)


def save_sheet(school_class, day, data, by):
    """data: {student_id: (status, note)}. Returns counts. Notifies the family only when a student newly becomes absent."""
    students = {s.id: s for s in class_students(school_class)}
    existing = {r.student_id: r for r in AttendanceRecord.objects.filter(school_class=school_class, date=day)}
    counts = defaultdict(int)
    for sid, (status, note) in data.items():
        if sid not in students or status not in STATUSES:
            continue
        old = existing.get(sid)
        rec, _ = AttendanceRecord.objects.update_or_create(
            student_id=sid, date=day, defaults={"school_class": school_class, "status": status, "note": note[:160], "marked_by": by})
        counts[status] += 1
        if status == "absent" and (old is None or old.status != "absent"):
            notify_family(students[sid], f"Marked absent on {day:%d %b %Y}", "If this is a mistake or there was a reason, please contact the class teacher or send a leave request.",
                          "/attendance/me/", f"/attendance/student/{sid}/", "attendance")
    return dict(counts)


def summary(student, start=None, end=None):
    """Attendance % = (present + late) / (present + late + absent). Approved leave is excused and left out."""
    qs = AttendanceRecord.objects.filter(student=student)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    c = {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id"))}
    present, late, absent, leave = (c.get(k, 0) for k in ("present", "late", "absent", "leave"))
    base = present + late + absent
    return {"present": present, "late": late, "absent": absent, "leave": leave, "marked": base + leave,
            "pct": round((present + late) * 100 / base, 1) if base else None}


def bulk_pct(student_ids, start, end):
    """{student_id: pct or None} in one query, for scans and reports."""
    agg = defaultdict(lambda: defaultdict(int))
    for sid, st, n in (AttendanceRecord.objects.filter(student_id__in=student_ids, date__range=(start, end))
                       .values_list("student_id", "status").annotate(n=Count("id"))):
        agg[sid][st] = n
    out = {}
    for sid in student_ids:
        a = agg.get(sid, {})
        base = a.get("present", 0) + a.get("late", 0) + a.get("absent", 0)
        out[sid] = round((a.get("present", 0) + a.get("late", 0)) * 100 / base, 1) if base else None
    return out


def class_report(classes, start, end):
    rows = []
    for c in classes.select_related("campus"):
        ids = list(class_students(c).values_list("pk", flat=True))
        pcts = bulk_pct(ids, start, end)
        vals = [p for p in pcts.values() if p is not None]
        rows.append({"cls": c, "students": len(ids), "avg": round(sum(vals) / len(vals), 1) if vals else None,
                     "low": sum(1 for p in vals if p < LOW_ATTENDANCE)})
    return rows


def staff_sheet(day, teachers):
    saved = {r.teacher_id: r for r in StaffAttendance.objects.filter(date=day, teacher__in=teachers)}
    return [{"teacher": t, "status": saved[t.id].status if t.id in saved else ""} for t in teachers]


def teachers_for(user):
    qs = User.objects.filter(role=User.Role.TEACHER, is_active=True)
    if user.is_super_admin:
        return qs
    ids = scope.campus_ids(user)
    return qs if ids is None else qs.filter(campus_id__in=ids)


def parse_range(request, days=30):
    def d(v, default):
        try:
            return date.fromisoformat(v)
        except (TypeError, ValueError):
            return default
    end = d(request.GET.get("to"), timezone.localdate())
    start = d(request.GET.get("from"), end - timedelta(days=days))
    return (start, end) if start <= end else (end, start)
