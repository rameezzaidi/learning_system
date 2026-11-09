from datetime import date, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.rbac import has_perm, perm_required
from core import audit, scope

from . import services
from .models import CalendarEvent, Period, Slot, Substitution, Term, WEEKDAYS


def _date(value, default=None):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def _time(value):
    try:
        h, m = value.split(":")[:2]
        return time(int(h), int(m))
    except (AttributeError, ValueError):
        return None


@login_required
def index(request):
    u = request.user
    if u.is_student or (u.is_parent and u.children.exists()):
        classes = list(services.classes_for_user(u))
        if len(classes) == 1:
            return redirect("timetable:class", pk=classes[0].pk)
        return render(request, "timetable/index.html", {"classes": classes, "page": "timetable"})
    if u.is_parent:
        raise PermissionDenied
    classes = services.classes_for_user(u).select_related("campus")
    return render(request, "timetable/index.html", {"classes": classes, "is_teacher": u.is_teacher, "page": "timetable"})


@login_required
def class_view(request, pk):
    from academics.models import SchoolClass
    cls = get_object_or_404(SchoolClass, pk=pk)
    if not services.can_view_class(request.user, cls):
        raise PermissionDenied
    today = timezone.localdate()
    cover = Substitution.objects.filter(slot__school_class=cls, date__gte=today, date__lte=today + timedelta(days=7)).select_related("substitute", "slot__period", "slot__course__subject")
    return render(request, "timetable/class.html", {"cls": cls, "g": services.class_grid(cls), "can_edit": services.can_manage(request.user, cls),
                                                   "cover": cover, "page": "timetable"})


@login_required
def mine(request):
    if not request.user.is_teacher:
        raise PermissionDenied
    today = timezone.localdate()
    cover = services.teacher_cover(request.user, today, today + timedelta(days=14))
    return render(request, "timetable/mine.html", {"g": services.teacher_grid(request.user), "cover": cover, "today": today, "page": "timetable"})


@login_required
def edit(request, pk):
    from academics.models import Course, SchoolClass
    cls = get_object_or_404(SchoolClass, pk=pk)
    if not services.can_manage(request.user, cls):
        raise PermissionDenied
    pers = [p for p in services.periods()]
    courses = list(Course.objects.filter(school_class=cls).select_related("subject", "teacher").order_by("subject__name"))
    posted = None
    if request.method == "POST":
        data = {}
        for d, _ in WEEKDAYS:
            for p in pers:
                v = request.POST.get(f"c_{d}_{p.pk}", "")
                data[(d, p.pk)] = int(v) if v.isdigit() else ""
        errors = services.save_grid(cls, data)
        if errors:
            for e in errors[:8]:
                messages.error(request, e)
            posted = data
        else:
            audit.record(request, "timetable.save", str(cls), f"{sum(1 for v in data.values() if v)} periods")
            messages.success(request, f"Timetable saved for {cls}.")
            return redirect("timetable:class", pk=cls.pk)
    g = services.class_grid(cls, editing=True)
    if posted is not None:
        for row in g["rows"]:
            row["selected"] = [posted.get((d[0], row["period"].pk)) for d in g["days"]]
    else:
        for row in g["rows"]:
            row["selected"] = [(c.course_id if c else "") for c in row["cells"]]
    for row in g["rows"]:
        row["pairs"] = list(zip(g["days"], row["selected"]))
    return render(request, "timetable/edit.html", {"cls": cls, "g": g, "courses": courses, "page": "timetable"})


@login_required
def periods(request):
    if not services.can_manage(request.user):
        raise PermissionDenied
    if request.method == "POST":
        act = request.POST.get("action")
        if act == "add":
            st, en = _time(request.POST.get("start_time")), _time(request.POST.get("end_time"))
            name = request.POST.get("name", "").strip()[:40]
            try:
                order = int(request.POST.get("order") or 0)
            except ValueError:
                order = 0
            if not (name and st and en and en > st and order > 0):
                messages.error(request, "Give a name, a start before the end time, and an order number (1, 2, 3…).")
            elif Period.objects.filter(order=order).exists():
                messages.error(request, f"Order {order} is already used.")
            else:
                Period.objects.create(name=name, start_time=st, end_time=en, order=order, is_break=bool(request.POST.get("is_break")))
                audit.record(request, "timetable.period", name, f"{st}-{en}")
                messages.success(request, "Period added.")
        elif act == "delete":
            p = Period.objects.filter(pk=request.POST.get("period") or 0).first()
            if p:
                n = p.slots.count()
                p.delete()
                audit.record(request, "timetable.period.delete", p.name, f"{n} lessons removed")
                messages.success(request, f"Period deleted{f' ({n} lessons removed from timetables)' if n else ''}.")
        return redirect("timetable:periods")
    nxt = (Period.objects.order_by("-order").first().order + 1) if Period.objects.exists() else 1
    return render(request, "timetable/periods.html", {"periods": Period.objects.all(), "next_order": nxt, "page": "tt_periods"})


@login_required
def substitutions(request):
    from attendance.services import teachers_for
    if not services.can_manage(request.user):
        raise PermissionDenied
    day = _date(request.GET.get("date") or request.POST.get("date"), timezone.localdate())
    teachers = list(teachers_for(request.user).order_by("first_name", "username"))
    if request.method == "POST":
        slot = get_object_or_404(Slot, pk=request.POST.get("slot") or 0, course__teacher__in=teachers)
        if request.POST.get("action") == "remove":
            Substitution.objects.filter(slot=slot, date=day).delete()
            messages.success(request, "Cover removed.")
        else:
            t = next((x for x in teachers if str(x.pk) == request.POST.get("substitute")), None)
            err = "Choose a teacher." if t is None else services.assign_substitute(slot, day, t, request.POST.get("reason", ""), request.user)
            if err:
                messages.error(request, err)
            else:
                audit.record(request, "timetable.substitute", f"{slot.school_class} {day}", t.username)
                messages.success(request, f"{t.display_name} will cover {slot.school_class} {slot.period.name}.")
        return redirect(f"/timetable/substitutions/?date={day.isoformat()}")
    rows = services.cover_rows(day, teachers)
    for r in rows:
        r["free"] = services.free_teachers(day, r["slot"].period_id, teachers)
    return render(request, "timetable/substitutions.html", {"rows": rows, "day": day, "page": "tt_subs"})


# ------------------------------------------------------------------ calendar
def _allowed_campuses(user):
    ids = scope.campus_ids(user)
    from organization.models import Campus
    qs = Campus.objects.filter(is_active=True)
    return qs if ids is None else qs.filter(pk__in=ids), ids is None


def _campus_value(user, raw):
    """(ok, campus_id or None)."""
    qs, all_ok = _allowed_campuses(user)
    if not raw:
        return all_ok, None
    c = qs.filter(pk=raw).first() if str(raw).isdigit() else None
    return c is not None, getattr(c, "pk", None)


@login_required
def calendar_view(request):
    u = request.user
    can = has_perm(u, "calendar.manage") and (u.is_super_admin or u.is_management)
    today = timezone.localdate()
    if request.method == "POST":
        if not can:
            raise PermissionDenied
        act = request.POST.get("action")
        if act in ("add_event", "add_term"):
            ok, cid = _campus_value(u, request.POST.get("campus"))
            s, e = _date(request.POST.get("start_date")), _date(request.POST.get("end_date")) or _date(request.POST.get("start_date"))
            title = request.POST.get("title", "").strip()[:120]
            if not (ok and s and e and title and e >= s):
                messages.error(request, "Check the title, dates (end on or after start) and campus.")
            elif act == "add_event":
                kind = request.POST.get("kind") if request.POST.get("kind") in dict(CalendarEvent.Kind.choices) else "event"
                CalendarEvent.objects.create(kind=kind, title=title, start_date=s, end_date=e, campus_id=cid, note=request.POST.get("note", "")[:300], created_by=u)
                audit.record(request, "calendar.event", title, f"{s} to {e}")
                messages.success(request, "Added to the calendar.")
            else:
                Term.objects.create(name=title, start_date=s, end_date=e, campus_id=cid)
                audit.record(request, "calendar.term", title, f"{s} to {e}")
                messages.success(request, "Term added.")
        elif act in ("delete_event", "delete_term"):
            model = CalendarEvent if act == "delete_event" else Term
            obj = model.objects.filter(pk=request.POST.get("id") or 0).first()
            if obj and _campus_value(u, obj.campus_id or "")[0]:
                audit.record(request, f"calendar.{act}", str(getattr(obj, "title", obj)), "")
                obj.delete()
                messages.success(request, "Removed.")
            else:
                raise PermissionDenied
        return redirect("timetable:calendar")
    raw = request.GET.get("month", "")
    try:
        y, m = (int(x) for x in raw.split("-"))
        first = date(y, m, 1)
    except (ValueError, TypeError):
        first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    prv = (first - timedelta(days=1)).replace(day=1)
    events = list(services.events_between(u, first, nxt - timedelta(days=1)))
    upcoming = services.events_between(u, today, today + timedelta(days=60))[:12]
    from organization.models import Campus
    return render(request, "timetable/calendar.html", {
        "weeks": services.month_weeks(first.year, first.month, events), "first": first, "prev": prv, "next": nxt, "today": today,
        "upcoming": upcoming, "terms": Term.objects.filter(services.campus_filter(u)).order_by("-start_date")[:8], "term": services.current_term(u, today),
        "can": can, "kinds": CalendarEvent.Kind.choices, "campuses": _allowed_campuses(u)[0] if can else [], "all_ok": _allowed_campuses(u)[1] if can else False,
        "page": "calendar"})
