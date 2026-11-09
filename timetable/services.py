import calendar
from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q

from accounts.models import User
from accounts.rbac import has_perm
from core import scope
from core.notify import notify

from .models import CalendarEvent, Period, Slot, Substitution, Term, WEEKDAYS


# ------------------------------------------------------------------ access
def can_view_class(user, cls):
    from academics.models import Course, Enrollment
    if user.is_super_admin:
        return True
    if user.is_management:
        return has_perm(user, "timetable.view") and scope.classes_for(user).filter(pk=cls.pk).exists()
    if user.is_teacher:
        return Course.objects.filter(teacher=user, school_class=cls).exists()
    if user.is_student:
        return Enrollment.objects.filter(student=user, school_class=cls).exists()
    if user.is_parent:
        return Enrollment.objects.filter(student__in=user.children.all(), school_class=cls).exists()
    return False


def can_manage(user, cls=None):
    if user.is_super_admin:
        return True
    if not (user.is_management and has_perm(user, "timetable.manage")):
        return False
    return cls is None or scope.classes_for(user).filter(pk=cls.pk).exists()


def classes_for_user(user):
    """Classes shown on the timetable index."""
    from academics.models import SchoolClass
    if user.is_super_admin or user.is_management:
        return scope.classes_for(user) if user.is_management else SchoolClass.objects.all()
    if user.is_teacher:
        return SchoolClass.objects.filter(courses__teacher=user).distinct()
    if user.is_student:
        return SchoolClass.objects.filter(enrollments__student=user)
    if user.is_parent:
        return SchoolClass.objects.filter(enrollments__student__in=user.children.all()).distinct()
    return SchoolClass.objects.none()


# ------------------------------------------------------------------ grids
def periods():
    return list(Period.objects.all())


def days_for(slots, editing=False):
    used = {s.weekday for s in slots}
    return [d for d in WEEKDAYS if d[0] < 5 or editing or d[0] in used]


def class_grid(cls, editing=False):
    pers = periods()
    slots = list(Slot.objects.filter(school_class=cls).select_related("course__subject", "course__teacher", "period"))
    by = {(s.weekday, s.period_id): s for s in slots}
    days = days_for(slots, editing)
    rows = [{"period": p, "cells": [by.get((d[0], p.id)) for d in days]} for p in pers]
    return {"days": days, "rows": rows, "count": len(slots)}


def teacher_grid(teacher):
    pers = periods()
    slots = list(Slot.objects.filter(course__teacher=teacher).select_related("course__subject", "school_class", "period"))
    by = {(s.weekday, s.period_id): s for s in slots}
    days = days_for(slots)
    rows = [{"period": p, "cells": [by.get((d[0], p.id)) for d in days]} for p in pers]
    return {"days": days, "rows": rows, "count": len(slots)}


def clash(teacher, weekday, period_id, exclude_class=None):
    """Another class slot where this teacher already teaches at the same time."""
    if teacher is None:
        return None
    qs = Slot.objects.filter(course__teacher=teacher, weekday=weekday, period_id=period_id).select_related("school_class", "period")
    if exclude_class is not None:
        qs = qs.exclude(school_class=exclude_class)
    return qs.first()


@transaction.atomic
def save_grid(cls, data):
    """data: {(weekday, period_id): course_id or ''}. All-or-nothing; returns a list of error strings."""
    from academics.models import Course
    courses = {c.pk: c for c in Course.objects.filter(school_class=cls).select_related("subject", "teacher")}
    pers = {p.pk: p for p in Period.objects.filter(is_break=False)}
    errors, wanted = [], {}
    day_names = dict(WEEKDAYS)
    for (wd, pid), cid in data.items():
        if wd not in day_names or pid not in pers or not cid:
            continue
        c = courses.get(int(cid))
        if c is None:
            errors.append(f"{day_names[wd]} {pers[pid].name}: that subject is not taught in {cls}.")
            continue
        other = clash(c.teacher, wd, pid, exclude_class=cls)
        if other:
            errors.append(f"{day_names[wd]} {pers[pid].name}: {c.teacher.display_name} already teaches {other.school_class} then.")
            continue
        wanted[(wd, pid)] = c
    if errors:
        transaction.set_rollback(True)
        return errors
    existing = {(s.weekday, s.period_id): s for s in Slot.objects.filter(school_class=cls)}
    for key, s in existing.items():
        if key not in wanted:
            s.delete()
    for (wd, pid), c in wanted.items():
        s = existing.get((wd, pid))
        if s is None:
            Slot.objects.create(school_class=cls, weekday=wd, period_id=pid, course=c)
        elif s.course_id != c.pk:
            s.course = c
            s.save()
    return []


# ------------------------------------------------------------------ substitutions
def absent_teachers(day, teachers):
    from attendance.models import StaffAttendance
    ids = set(StaffAttendance.objects.filter(date=day, status__in=["absent", "leave"], teacher__in=teachers).values_list("teacher_id", flat=True))
    return [t for t in teachers if t.id in ids]


def cover_rows(day, teachers):
    """Slots that need cover on `day` because the teacher is marked absent/on leave."""
    wd = day.weekday()
    gone = absent_teachers(day, teachers)
    slots = (Slot.objects.filter(weekday=wd, course__teacher__in=gone)
             .select_related("school_class", "period", "course__subject", "course__teacher").order_by("period__order"))
    subs = {s.slot_id: s for s in Substitution.objects.filter(date=day, slot__in=slots).select_related("substitute")}
    return [{"slot": s, "sub": subs.get(s.id)} for s in slots]


def free_teachers(day, period_id, candidates):
    wd = day.weekday()
    busy = set(Slot.objects.filter(weekday=wd, period_id=period_id).values_list("course__teacher_id", flat=True))
    busy |= set(Substitution.objects.filter(date=day, slot__period_id=period_id).values_list("substitute_id", flat=True))
    gone = {t.id for t in absent_teachers(day, candidates)}
    return [t for t in candidates if t.id not in busy and t.id not in gone]


def assign_substitute(slot, day, teacher, reason, by):
    if day.weekday() != slot.weekday:
        return "That slot is not on this weekday."
    if teacher.id not in {t.id for t in free_teachers(day, slot.period_id, [teacher])}:
        return f"{teacher.display_name} is not free in that period."
    Substitution.objects.update_or_create(slot=slot, date=day, defaults={"substitute": teacher, "reason": reason[:160], "created_by": by})
    notify(teacher, f"Cover: {slot.school_class} {slot.period.name}", f"{day:%a %d %b}, {slot.course.subject.name}", "/timetable/mine/", "timetable")
    return None


def teacher_cover(teacher, start, end):
    return Substitution.objects.filter(substitute=teacher, date__range=(start, end)).select_related("slot__school_class", "slot__period", "slot__course__subject")


# ------------------------------------------------------------------ calendar
def campus_filter(user):
    """Q for events/terms a user should see: all-campus ones plus their campuses'."""
    if user.is_student:
        cid = getattr(getattr(user, "student_profile", None), "campus_id", None)
        ids = [cid] if cid else []
    elif user.is_parent:
        ids = [c for c in (getattr(getattr(k, "student_profile", None), "campus_id", None) for k in user.children.all()) if c]
    elif user.is_teacher:
        ids = [user.campus_id] if user.campus_id else None
    else:
        ids = scope.campus_ids(user)
    return Q() if ids is None else Q(campus__isnull=True) | Q(campus_id__in=ids)


def events_between(user, start, end):
    return CalendarEvent.objects.filter(campus_filter(user), start_date__lte=end, end_date__gte=start).select_related("campus")


def month_weeks(year, month, events):
    by = defaultdict(list)
    for e in events:
        d = max(e.start_date, date(year, month, 1))
        last = min(e.end_date, date(year, month, calendar.monthrange(year, month)[1]))
        while d <= last:
            by[d].append(e)
            d += timedelta(days=1)
    return [[{"day": d, "in_month": d.month == month, "events": by.get(d, [])} for d in week]
            for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)]


def holiday_on(day, campus_id=None):
    qs = CalendarEvent.objects.filter(kind="holiday", start_date__lte=day, end_date__gte=day)
    qs = qs.filter(Q(campus__isnull=True) | Q(campus_id=campus_id)) if campus_id else qs.filter(campus__isnull=True)
    return qs.first()


def current_term(user, day):
    return Term.objects.filter(campus_filter(user), start_date__lte=day, end_date__gte=day).first()
