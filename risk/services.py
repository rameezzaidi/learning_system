from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from accounts.models import User
from accounts.rbac import has_perm
from attendance.models import AttendanceRecord
from core import scope

from .models import Alert, EarlyWarningSettings


def students_in_scope(user):
    """Students whose alerts this user may see."""
    if user.is_super_admin:
        return User.objects.filter(role=User.Role.STUDENT)
    if user.is_management:
        return scope.students_for(user)
    if user.is_teacher:
        return User.objects.filter(role=User.Role.STUDENT, enrollment__school_class__courses__teacher=user).distinct()
    return User.objects.none()


def can_view(user, perm="risk.view"):
    return has_perm(user, perm) and (user.is_super_admin or user.is_management or user.is_teacher)


def alerts_for(user):
    return Alert.objects.filter(student__in=students_in_scope(user)).select_related("student__student_profile__campus")


def open_count(user):
    if not can_view(user):
        return 0
    return alerts_for(user).exclude(status="resolved").count()


# ------------------------------------------------------------------ signals
def _attendance(ids, cfg):
    end = timezone.localdate()
    start = end - timedelta(days=cfg.window_days)
    agg = defaultdict(lambda: defaultdict(int))
    for sid, st, n in (AttendanceRecord.objects.filter(student_id__in=ids, date__range=(start, end))
                       .values_list("student_id", "status").annotate(n=Count("id"))):
        agg[sid][st] = n
    out = {}
    for sid, a in agg.items():
        base = a.get("present", 0) + a.get("late", 0) + a.get("absent", 0)
        if base >= 3:
            pct = (a.get("present", 0) + a.get("late", 0)) * 100 / base
            if pct < cfg.attendance_below:
                out[sid] = f"Attendance {round(pct)}% in the last {cfg.window_days} days (below {cfg.attendance_below}%)"
    return out


def _exams(ids, cfg):
    from exams import grading
    from exams.models import Exam
    per_student = defaultdict(list)  # sid -> [(exam, pct)] oldest first
    for e in Exam.objects.filter(is_published=True).select_related("school_class").order_by("start_date", "id"):
        for r in grading.compute(e)["rows"]:
            if r["pct"] is not None and r["student"].id in ids:
                per_student[r["student"].id].append((e, float(r["pct"])))
    out = defaultdict(list)
    for sid, lst in per_student.items():
        e, pct = lst[-1]
        if pct < cfg.exam_below:
            out[sid].append(f"{e.name}: {round(pct)}% (below {cfg.exam_below}%)")
        if len(lst) > 1 and lst[-2][1] - pct >= cfg.exam_drop:
            out[sid].append(f"Exam score fell {round(lst[-2][1] - pct)} points since {lst[-2][0].name}")
    return out


def _quizzes(ids, cfg):
    from assessments.models import Attempt
    vals = defaultdict(list)
    for sid, score, total in Attempt.objects.filter(student_id__in=ids, submitted_at__isnull=False).values_list("student_id", "score", "total"):
        if total:
            vals[sid].append(score * 100 / total)
    return {sid: f"Quiz average {round(sum(v) / len(v))}% over {len(v)} quizzes (below {cfg.quiz_below}%)"
            for sid, v in vals.items() if len(v) >= 2 and sum(v) / len(v) < cfg.quiz_below}


def _nuggets(ids, cfg):
    from nuggets.models import StudentNugget
    rows = (StudentNugget.objects.filter(student_id__in=ids, status="assigned", attempts__gte=2)
            .values_list("student_id").annotate(n=Count("id")))
    return {sid: f"{n} learning nuggets tried several times and still not mastered" for sid, n in rows if n >= cfg.struggling_nuggets}


def signals(student_ids=None):
    """{student_id: [reason, ...]} for students with at least `min_signals` signals."""
    cfg = EarlyWarningSettings.get()
    ids = set(student_ids) if student_ids is not None else set(User.objects.filter(role=User.Role.STUDENT, is_active=True).values_list("pk", flat=True))
    found = defaultdict(list)
    for sid, msg in _attendance(ids, cfg).items():
        found[sid].append(msg)
    for sid, msgs in _exams(ids, cfg).items():
        found[sid] += msgs
    for fn in (_quizzes, _nuggets):
        for sid, msg in fn(ids, cfg).items():
            found[sid].append(msg)
    return {sid: r for sid, r in found.items() if len(r) >= max(cfg.min_signals, 1)}


def level_for(n):
    return Alert.Level.HIGH if n >= 3 else Alert.Level.MEDIUM if n == 2 else Alert.Level.WATCH


@transaction.atomic
def scan():
    """Raise or refresh alerts. Idempotent: one active alert per student. Only still-'open' alerts auto-resolve."""
    found = signals()
    created = updated = resolved = 0
    active = {a.student_id: a for a in Alert.objects.exclude(status="resolved")}
    for sid, reasons in found.items():
        lvl = level_for(len(reasons))
        a = active.get(sid)
        if a is None:
            Alert.objects.create(student_id=sid, level=lvl, reasons=reasons)
            created += 1
        elif a.reasons != reasons or a.level != lvl:
            a.level, a.reasons = lvl, reasons
            a.save()
            updated += 1
    for sid, a in active.items():
        if sid not in found and a.status == Alert.Status.OPEN:
            a.status, a.resolved_at, a.resolution_note = Alert.Status.RESOLVED, timezone.now(), "Auto-closed: no warning signs in the latest scan"
            a.save()
            resolved += 1
    return {"created": created, "updated": updated, "resolved": resolved, "flagged": len(found)}
