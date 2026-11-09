"""Coverage numbers and the handover snapshot. No request objects in here."""
from datetime import date

from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import User
from core import scope
from core.notify import notify

STALE_DAYS = 14
GAP_POINTS = 20


def coverage(course):
    agg = course.topics.aggregate(n=Count("id"), done=Count("id", filter=Q(is_covered=True)))
    last = course.topics.filter(is_covered=True).order_by("-covered_on", "-id").first()
    n, done = agg["n"], agg["done"]
    return {"total": n, "done": done, "pct": round(done * 100 / n) if n else None,
            "last_on": last.covered_on if last else None, "last_title": last.title if last else "",
            "stale_days": (date.today() - last.covered_on).days if last and last.covered_on else None}


def courses_for(user):
    """Courses this user may see in the curriculum screens."""
    from academics.models import Course
    qs = Course.objects.select_related("subject", "school_class__campus__region", "teacher")
    if user.is_super_admin:
        return qs
    if user.is_management:
        ids = scope.campus_ids(user)
        return qs if ids is None else qs.filter(Q(school_class__campus_id__in=ids) | Q(school_class__campus__isnull=True))
    if user.is_teacher:
        from .models import Handover
        cover = Handover.objects.filter(to_teacher=user, kind="absence").exclude(status="closed").values("course_id")
        return qs.filter(Q(teacher=user) | Q(pk__in=cover))
    return qs.none()


def can_edit_outline(user, course):
    if user.is_super_admin or course.teacher_id == user.id:
        return True
    if user.role == User.Role.PRINCIPAL and scope.campus_ids(user) is not None:
        ids = scope.campus_ids(user)
        return course.school_class.campus_id in ids
    if user.is_teacher:
        from .models import Handover
        return Handover.objects.filter(course=course, to_teacher=user, kind="absence").exclude(status="closed").exists()
    return False


def snapshot(course):
    """Everything the next teacher needs, as plain JSON."""
    from assessments.grading import student_summary
    from assessments.models import Assessment
    from nuggets.models import StudentNugget
    from academics.models import HelpRequest, Enrollment

    topics = list(course.topics.all())
    done = [t for t in topics if t.is_covered]
    pending = [t for t in topics if not t.is_covered]
    chapters = {}
    for t in topics:
        key = (t.unit, t.chapter or "General")
        chapters.setdefault(key, []).append(t)
    completed_ch = [f"{u + ' › ' if u else ''}{c}" for (u, c), ts in chapters.items() if all(x.is_covered for x in ts)]
    last = max(done, key=lambda t: (t.covered_on or date.min, t.id), default=None)

    students = [e.student for e in Enrollment.objects.filter(school_class=course.school_class).select_related("student")]
    attention = []
    for st in students:
        reasons = []
        avg = student_summary(st, [course])[0]["avg"]
        if avg is not None and avg < 60:
            reasons.append(f"quiz average {avg}%")
        struggling = StudentNugget.objects.filter(student=st, nugget__course=course, nugget__is_published=True, status="assigned", attempts__gte=2).count()
        if struggling:
            reasons.append(f"{struggling} nugget{'s' if struggling > 1 else ''} not mastered after 2+ tries")
        if reasons:
            attention.append({"student": st.display_name, "reasons": "; ".join(reasons)})

    assessments = []
    for a in Assessment.objects.filter(course=course).order_by("-created_at")[:8]:
        assessments.append({"title": a.title, "kind": a.get_kind_display(), "published": a.is_published})

    return {
        "taken_at": timezone.now().isoformat(timespec="minutes"),
        "course": f"{course.subject} · {course.school_class}",
        "total": len(topics), "done": len(done), "pct": round(len(done) * 100 / len(topics)) if topics else None,
        "last_title": last.title if last else "", "last_on": last.covered_on.isoformat() if last and last.covered_on else "",
        "completed_chapters": completed_ch,
        "completed_topics": [t.title for t in done][-10:],
        "next_topics": [{"title": t.title, "chapter": t.chapter, "outcome": t.outcome} for t in pending[:6]],
        "pending_count": len(pending),
        "lessons": course.published_lessons().count(),
        "assessments": assessments,
        "open_help": HelpRequest.objects.filter(course=course).exclude(status="resolved").count(),
        "attention": attention[:25], "n_students": len(students),
    }


def create_handover(course, from_teacher, to_teacher, kind, reason="", by=None, expected_return=None):
    from .models import Handover
    h = Handover.objects.create(course=course, from_teacher=from_teacher, to_teacher=to_teacher, kind=kind, reason=reason[:300],
                                created_by=by, expected_return=expected_return, snapshot=snapshot(course))
    url = f"/curriculum/handovers/{h.pk}/"
    label = f"{course.subject} · {course.school_class}"
    if to_teacher:
        notify(to_teacher, f"Handover: {label}", "Open the handover report to continue from the exact topic where the last teacher stopped.", url, "handover")
    for p in _supervisors(course):
        if p.pk not in {getattr(to_teacher, "pk", None), getattr(by, "pk", None)}:
            notify(p, f"Teacher handover: {label}", f"{getattr(from_teacher, 'display_name', 'Nobody')} → {getattr(to_teacher, 'display_name', 'nobody')}", url, "handover")
    return h


def _supervisors(course):
    cid = course.school_class.campus_id
    qs = User.objects.filter(is_active=True).filter(
        Q(role=User.Role.PRINCIPAL, campus_id=cid) if cid else Q(pk__in=[])
    )
    return list(qs)


def overdue_handovers():
    from .models import Handover
    cutoff = timezone.now() - timezone.timedelta(days=3)
    return Handover.objects.filter(status="pending", created_at__lt=cutoff)
