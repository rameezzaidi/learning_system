import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.rbac import has_perm, perm_required
from core import audit, scope
from core.notify import notify

from . import services
from .models import Handover, Topic


def _course(request, pk):
    return get_object_or_404(services.courses_for(request.user), pk=pk)


def _csv_safe(v):
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v


# ------------------------------------------------------------------ outline & coverage
@login_required
def index(request):
    if not (request.user.is_super_admin or request.user.is_teacher or request.user.is_management):
        raise PermissionDenied
    rows = [{"course": c, "cov": services.coverage(c)} for c in services.courses_for(request.user)]
    return render(request, "curriculum/index.html", {"rows": rows, "page": "curriculum"})


@login_required
def outline(request, pk):
    course = _course(request, pk)
    me = request.user
    can_edit = services.can_edit_outline(me, course)
    topics = list(course.topics.select_related("covered_by"))
    groups = []
    for t in topics:
        key = (t.unit, t.chapter)
        if not groups or groups[-1]["key"] != key:
            groups.append({"key": key, "unit": t.unit, "chapter": t.chapter, "topics": []})
        groups[-1]["topics"].append(t)
    for g in groups:
        g["done"] = sum(1 for t in g["topics"] if t.is_covered)
    others = services.courses_for(me).filter(subject=course.subject, topics__isnull=False).exclude(pk=course.pk).distinct() if can_edit else []
    return render(request, "curriculum/outline.html", {
        "course": course, "groups": groups, "cov": services.coverage(course), "can_edit": can_edit, "others": others,
        "handovers": course.handovers.select_related("from_teacher", "to_teacher")[:5], "page": "curriculum",
        "can_handover": me.is_super_admin or course.teacher_id == me.id or has_perm(me, "handover.create"),
    })


def _guard_edit(request, course):
    if not services.can_edit_outline(request.user, course):
        raise PermissionDenied


@login_required
@require_POST
def topic_toggle(request, pk):
    t = get_object_or_404(Topic.objects.select_related("course"), pk=pk)
    _guard_edit(request, t.course)
    t.is_covered = not t.is_covered
    t.covered_on = timezone.localdate() if t.is_covered else None
    t.covered_by = request.user if t.is_covered else None
    t.note = request.POST.get("note", "")[:240] if t.is_covered else ""
    t.save()
    audit.record(request, "curriculum.covered" if t.is_covered else "curriculum.uncovered", t.title, f"course={t.course_id}")
    return redirect("curriculum:outline", pk=t.course_id)


@login_required
@require_POST
def topic_delete(request, pk):
    t = get_object_or_404(Topic.objects.select_related("course"), pk=pk)
    _guard_edit(request, t.course)
    cid = t.course_id
    t.delete()
    return redirect("curriculum:outline", pk=cid)


@login_required
@require_POST
def topics_add(request, pk):
    course = _course(request, pk)
    _guard_edit(request, course)
    start = (course.topics.order_by("-position").values_list("position", flat=True).first() or 0) + 1
    added = 0
    for line in request.POST.get("lines", "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts] if any(parts) else []
        if not parts:
            continue
        unit, chapter, title, outcome = "", "", "", ""
        if len(parts) == 1:
            title = parts[0]
        elif len(parts) == 2:
            chapter, title = parts
        elif len(parts) == 3:
            unit, chapter, title = parts
        else:
            unit, chapter, title, outcome = parts[0], parts[1], parts[2], " | ".join(parts[3:])
        if not title:
            continue
        Topic.objects.create(course=course, unit=unit[:120], chapter=chapter[:160], title=title[:200], outcome=outcome, position=start + added)
        added += 1
    if added:
        audit.record(request, "curriculum.add", f"course {course.pk}", f"{added} topics")
        messages.success(request, f"{added} topic{'s' if added != 1 else ''} added.")
    else:
        messages.error(request, "Nothing to add. Use one topic per line: Unit | Chapter | Topic | Learning outcome.")
    return redirect("curriculum:outline", pk=course.pk)


@login_required
@require_POST
def topics_copy(request, pk):
    course = _course(request, pk)
    _guard_edit(request, course)
    src = get_object_or_404(services.courses_for(request.user), pk=request.POST.get("source") or 0)
    start = (course.topics.order_by("-position").values_list("position", flat=True).first() or 0) + 1
    n = 0
    for t in src.topics.all():
        Topic.objects.create(course=course, unit=t.unit, chapter=t.chapter, title=t.title, outcome=t.outcome, position=start + n)
        n += 1
    audit.record(request, "curriculum.copy", f"course {course.pk}", f"from {src.pk}, {n} topics")
    messages.success(request, f"Copied {n} topics from {src}. Coverage starts fresh.")
    return redirect("curriculum:outline", pk=course.pk)


# ------------------------------------------------------------------ coverage monitor
@login_required
@perm_required("curriculum.monitor")
def monitor(request):
    from collections import defaultdict
    rows = []
    for c in services.courses_for(request.user):
        cov = services.coverage(c)
        cp = c.school_class.campus
        rows.append({"course": c, "cov": cov, "campus": cp.name if cp else "Whole school", "region": cp.region.name if cp else "",
                     "stale": cov["stale_days"] is not None and cov["stale_days"] > services.STALE_DAYS and (cov["pct"] or 0) < 100,
                     "empty": cov["total"] == 0})
    by_key = defaultdict(list)
    for r in rows:
        if r["cov"]["pct"] is not None:
            by_key[(r["course"].school_class.name, r["course"].subject.name)].append(r["cov"]["pct"])
    gaps = [{"grade": g, "subject": s, "min": min(v), "max": max(v), "spread": max(v) - min(v), "n": len(v)}
            for (g, s), v in by_key.items() if len(v) > 1 and max(v) - min(v) >= services.GAP_POINTS]
    gaps.sort(key=lambda x: -x["spread"])
    camp = defaultdict(list)
    for r in rows:
        if r["cov"]["pct"] is not None:
            camp[r["campus"]].append(r["cov"]["pct"])
    campus_avg = sorted(({"campus": k, "avg": round(sum(v) / len(v)), "n": len(v)} for k, v in camp.items()), key=lambda x: -x["avg"])
    rows.sort(key=lambda r: (r["cov"]["pct"] is None, r["cov"]["pct"] or 0))
    if request.GET.get("format") == "csv":
        if not has_perm(request.user, "reports.export"):
            raise PermissionDenied
        audit.record(request, "export.coverage", "curriculum", f"{len(rows)} rows")
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="curriculum-coverage.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Region", "Campus", "Class", "Subject", "Teacher", "Topics", "Covered", "Coverage %", "Last covered"])
        for r in rows:
            w.writerow([_csv_safe(x) for x in (r["region"], r["campus"], str(r["course"].school_class), r["course"].subject.name,
                        r["course"].teacher.display_name if r["course"].teacher else "", r["cov"]["total"], r["cov"]["done"],
                        r["cov"]["pct"] if r["cov"]["pct"] is not None else "", r["cov"]["last_on"] or "")])
        return resp
    return render(request, "curriculum/monitor.html", {"rows": rows, "gaps": gaps, "campus_avg": campus_avg, "stale_days": services.STALE_DAYS,
                                                       "can_export": has_perm(request.user, "reports.export"), "page": "coverage"})


# ------------------------------------------------------------------ handovers
def _handover_qs(user):
    qs = Handover.objects.select_related("course__subject", "course__school_class__campus", "from_teacher", "to_teacher")
    if user.is_super_admin:
        return qs
    if user.is_management and has_perm(user, "handover.view"):
        ids = scope.campus_ids(user)
        return qs if ids is None else qs.filter(course__school_class__campus_id__in=ids)
    if user.is_teacher:
        from django.db.models import Q
        return qs.filter(Q(from_teacher=user) | Q(to_teacher=user))
    return qs.none()


@login_required
def handover_list(request):
    status = request.GET.get("status", "")
    qs = _handover_qs(request.user)
    if status in dict(Handover.Status.choices):
        qs = qs.filter(status=status)
    rows = list(qs[:200])
    now = timezone.now()
    for h in rows:
        h.overdue = h.status == "pending" and (now - h.created_at).days >= 3
    return render(request, "curriculum/handovers.html", {"rows": rows, "status": status, "statuses": Handover.Status.choices, "page": "handovers"})


@login_required
def handover_detail(request, pk):
    h = get_object_or_404(_handover_qs(request.user), pk=pk)
    me = request.user
    can_close = h.status != "closed" and (me.is_super_admin or h.from_teacher_id == me.id or h.created_by_id == me.id or has_perm(me, "handover.create"))
    return render(request, "curriculum/handover_detail.html", {
        "h": h, "s": h.snapshot, "can_ack": h.status == "pending" and h.to_teacher_id == me.id, "can_close": can_close,
        "live": services.coverage(h.course), "page": "handovers"})


@login_required
@require_POST
def handover_ack(request, pk):
    h = get_object_or_404(_handover_qs(request.user), pk=pk)
    if h.to_teacher_id != request.user.id or h.status != "pending":
        raise PermissionDenied
    h.status, h.acknowledged_at, h.ack_note = "acknowledged", timezone.now(), request.POST.get("note", "")[:300]
    h.save()
    audit.record(request, "handover.ack", str(h.course), f"handover={h.pk}")
    for p in services._supervisors(h.course):
        notify(p, f"Handover acknowledged: {h.course}", f"{request.user.display_name} has taken over.", f"/curriculum/handovers/{h.pk}/", "handover")
    messages.success(request, "Handover acknowledged. You can now continue from the last covered topic.")
    return redirect("curriculum:handover_detail", pk=h.pk)


@login_required
@require_POST
def handover_close(request, pk):
    h = get_object_or_404(_handover_qs(request.user), pk=pk)
    me = request.user
    if not (me.is_super_admin or h.from_teacher_id == me.id or h.created_by_id == me.id or has_perm(me, "handover.create")):
        raise PermissionDenied
    h.status = "closed"
    h.save(update_fields=["status"])
    audit.record(request, "handover.close", str(h.course), f"handover={h.pk}")
    messages.success(request, "Cover ended.")
    return redirect("curriculum:handover_detail", pk=h.pk)


@login_required
def handover_new(request, pk):
    course = get_object_or_404(services.courses_for(request.user), pk=pk)
    me = request.user
    if not (me.is_super_admin or course.teacher_id == me.id or has_perm(me, "handover.create")):
        raise PermissionDenied
    teachers = User.objects.filter(role=User.Role.TEACHER, is_active=True).exclude(pk=course.teacher_id or 0)
    if request.method == "POST":
        to = teachers.filter(pk=request.POST.get("to") or 0).first()
        kind = request.POST.get("kind")
        if not to or kind not in ("absence", "transfer"):
            messages.error(request, "Choose the teacher who will take over.")
        else:
            reason = request.POST.get("reason", "")
            ret = request.POST.get("expected_return") or None
            if kind == "transfer":
                course.teacher = to  # the signal records the handover
                course.save()
                audit.record(request, "handover.transfer", str(course), f"to={to.username}")
                h = course.handovers.first()
                if h:
                    h.reason, h.created_by = reason or h.reason, me
                    h.save(update_fields=["reason", "created_by"])
            else:
                h = services.create_handover(course, course.teacher, to, "absence", reason, me, ret or None)
                audit.record(request, "handover.absence", str(course), f"cover={to.username}")
            messages.success(request, f"Handover sent to {to.display_name}.")
            return redirect("curriculum:handover_detail", pk=h.pk)
    return render(request, "curriculum/handover_form.html", {"course": course, "teachers": teachers, "page": "handovers"})
