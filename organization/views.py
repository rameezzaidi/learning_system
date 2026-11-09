from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User

from .forms import CampusForm, RegionForm, StudentForm, SyncSettingsForm
from .models import Campus, Region, StudentProfile, SyncRun, SyncSettings
from .queries import student_queryset
from django.conf import settings

from .services import (
    get_connector, is_running, oracle_configured, oracle_target, start_background_sync,
)

from accounts.rbac import has_perm, perm_required
from core import audit, scope

ADMIN = "super_admin"
admin_only = lambda v: login_required(role_required(ADMIN)(v))  # noqa: E731
perm = lambda *codes: (lambda v: login_required(perm_required(*codes)(v)))  # noqa: E731


# ---------- Regions & campuses ----------

@perm("campuses.view")
def overview(request):
    visible = scope.campuses_for(request.user)
    campuses = visible.annotate(n_students=Count("students"))
    regions = Region.objects.filter(campuses__in=visible).distinct().prefetch_related(Prefetch("campuses", queryset=campuses))
    data = []
    for r in regions:
        cs = list(r.campuses.all())
        data.append({"region": r, "campuses": cs, "students": sum(c.n_students for c in cs)})
    unassigned = 0
    if scope.campus_ids(request.user) is None:
        unassigned = User.objects.filter(role="student").filter(
            Q(student_profile__isnull=True) | Q(student_profile__campus__isnull=True)
        ).count()
    return render(request, "organization/overview.html", {"data": data, "unassigned": unassigned, "page": "org",
                                                          "can_manage": has_perm(request.user, "campuses.manage")})


def _guard_external(request, obj):
    if obj.is_external:
        messages.error(request, f"“{obj.name}” is managed by Oracle and cannot be changed here.")
        return True
    return False


@perm("campuses.manage")
def region_form(request, pk=None):
    obj = get_object_or_404(Region, pk=pk) if pk else None
    if obj and _guard_external(request, obj):
        return redirect("organization:overview")
    form = RegionForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Region saved.")
        return redirect("organization:overview")
    return render(request, "academics/form.html", {
        "form": form, "page": "org", "title": "Edit region" if obj else "New region", "back": "organization:overview",
    })


@perm("campuses.manage")
@require_POST
def region_delete(request, pk):
    obj = get_object_or_404(Region, pk=pk)
    if not _guard_external(request, obj):
        try:
            obj.delete()
            messages.success(request, "Region deleted.")
        except ProtectedError:
            messages.error(request, "This region still has campuses. Remove or move them first.")
    return redirect("organization:overview")


@perm("campuses.manage")
def campus_form(request, pk=None):
    obj = get_object_or_404(Campus, pk=pk) if pk else None
    if obj and _guard_external(request, obj):
        return redirect("organization:overview")
    initial = {"region": request.GET.get("region")} if not obj else None
    form = CampusForm(request.POST or None, instance=obj, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Campus saved.")
        return redirect("organization:overview")
    return render(request, "academics/form.html", {
        "form": form, "page": "org", "title": "Edit campus" if obj else "New campus", "back": "organization:overview",
    })


@perm("campuses.manage")
@require_POST
def campus_delete(request, pk):
    obj = get_object_or_404(Campus, pk=pk)
    if not _guard_external(request, obj):
        obj.delete()
        messages.success(request, "Campus deleted. Its students are now without a campus.")
    return redirect("organization:overview")


# ---------- Students ----------

@perm("students.view")
def student_list(request):
    g = request.GET
    qs = student_queryset(g, request.user)
    page = Paginator(qs.order_by("first_name", "username"), 50).get_page(g.get("page"))
    params = g.copy()
    params.pop("page", None)
    return render(request, "organization/student_list.html", {
        "page_obj": page, "campuses": scope.campuses_for(request.user),
        "regions": Region.objects.filter(campuses__in=scope.campuses_for(request.user)).distinct(),
        "can_create": has_perm(request.user, "students.create"), "can_edit": has_perm(request.user, "students.edit"),
        "can_export": has_perm(request.user, "students.export"),
        "f": {k: g.get(k, "") for k in ("region", "campus", "source", "status", "q")},
        "qs": params.urlencode(), "page": "students",
    })


@perm("students.create")
def student_create(request):
    form = StudentForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        u = form.save()
        audit.record(request, "student.create", u.username, f"campus={form.cleaned_data.get('campus') or '-'}")
        messages.success(request, f"{u.display_name} added.")
        return redirect("organization:student_list")
    return render(request, "organization/student_form.html", {"form": form, "page": "students", "title": "Add student"})


@perm("students.edit")
def student_edit(request, pk):
    u = get_object_or_404(scope.students_for(request.user), pk=pk)
    profile = StudentProfile.objects.filter(user=u).first()
    if profile and profile.is_external:
        messages.info(request, f"{u.display_name} comes from Oracle. Change the data in Oracle; it syncs automatically.")
        return redirect("organization:student_list")
    form = StudentForm(request.POST or None, user=u, actor=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request, "student.edit", u.username)
        messages.success(request, "Student updated.")
        return redirect("organization:student_list")
    return render(request, "organization/student_form.html", {
        "form": form, "page": "students", "title": f"Edit {u.display_name}", "edit": True,
    })


# ---------- Oracle sync ----------

@admin_only
def sync_page(request):
    cfg = SyncSettings.load()
    form = SyncSettingsForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Sync settings saved.")
        return redirect("organization:sync")
    runs = SyncRun.objects.all()[:15]
    return render(request, "organization/sync.html", {
        "form": form, "runs": runs, "running": is_running(), "configured": oracle_configured(),
        "target": oracle_target(), "mock": settings.ORACLE_MOCK, "page": "sync",
        "counts": {
            "regions": Region.objects.filter(source="oracle").count(),
            "campuses": Campus.objects.filter(source="oracle").count(),
            "students": StudentProfile.objects.filter(source="oracle").count(),
        },
    })


@admin_only
@require_POST
def sync_test(request):
    try:
        get_connector().ping()
        messages.success(request, "Connection to Oracle works.")
    except Exception as e:
        messages.error(request, f"Could not connect to Oracle: {e}")
    return redirect("organization:sync")


@admin_only
@require_POST
def sync_now(request):
    if is_running():
        messages.info(request, "A sync is already running.")
    elif not oracle_configured():
        messages.error(request, "Oracle connection is not configured. Set the ORACLE_* environment variables first.")
    else:
        start_background_sync("manual")
        messages.success(request, "Sync started. This page refreshes until it finishes.")
    return redirect("organization:sync")


# ------------------------------------------------------------------ student profile (term-wise record)
def _can_view_profile(user, student):
    from academics.models import Course, student_class
    if user.is_super_admin or user.pk == student.pk:
        return True
    if user.is_management:
        return has_perm(user, "students.view") and scope.can_see_student(user, student)
    if user.is_parent:
        return user.children.filter(pk=student.pk).exists()
    if user.is_teacher:
        cls = student_class(student)
        return bool(cls) and Course.objects.filter(teacher=user, school_class=cls).exists()
    return False


@login_required
def student_profile(request, pk):
    import json

    from django.core.exceptions import PermissionDenied

    from academics.models import course_rows, student_class
    from assessments.grading import student_summary
    from chat.permissions import can_chat
    from exams import grading, insights
    from exams.models import Exam

    student = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    me = request.user
    if not _can_view_profile(me, student):
        raise PermissionDenied
    staff = me.is_super_admin or me.is_teacher or me.is_management
    cls = student_class(student)

    exams = Exam.objects.filter(papers__marks__student=student).select_related("school_class").distinct()
    if not staff:
        exams = exams.filter(is_published=True)
    exams = sorted(exams, key=lambda e: (e.start_date is None, e.start_date or e.created_at.date(), e.id))

    terms, subjects = [], []
    for e in exams:
        res = grading.compute(e)
        row = grading.row_for(res, student.id)
        if not row:
            continue
        ins = insights.student_insights(res, row, None)
        subs = [{"subject": x["subject"], "marks": x["marks"], "total": x["total"], "pct": x["pct"], "grade": x["grade"], "class_avg": x["class_avg"], "status": x["status"]}
                for x in ins["subjects"]]
        for x in subs:
            if x["subject"] not in subjects:
                subjects.append(x["subject"])
        terms.append({"exam": e, "pct": ins["overall_pct"], "grade": ins["grade"], "gpa": ins["gpa"], "rank": ins["rank"], "n_ranked": ins["n_ranked"],
                      "result": ins["result"], "subjects": subs, "weak": ins["weak"], "strong": ins["strong"], "delta": None})
    for i, t in enumerate(terms):
        if i and t["pct"] is not None and terms[i - 1]["pct"] is not None:
            t["delta"] = round(t["pct"] - terms[i - 1]["pct"], 1)

    matrix = []
    for s in subjects:
        cells = []
        for t in terms:
            hit = next((x for x in t["subjects"] if x["subject"] == s), None)
            cells.append(hit)
        pcts = [c["pct"] for c in cells if c and c["pct"] is not None]
        trend = None
        if len(pcts) >= 2:
            trend = round(pcts[-1] - pcts[-2], 1)
        matrix.append({"subject": s, "cells": cells, "avg": round(sum(pcts) / len(pcts), 1) if pcts else None, "trend": trend})

    scored = [t for t in terms if t["pct"] is not None]
    kpi = {
        "latest": scored[-1] if scored else None,
        "avg": round(sum(t["pct"] for t in scored) / len(scored), 1) if scored else None,
        "best": max(scored, key=lambda t: t["pct"]) if scored else None,
    }
    trend_chart = json.dumps({"type": "line", "labels": [t["exam"].name[:14] for t in scored], "values": [t["pct"] for t in scored], "unit": "%", "max": 100}, default=float) if scored else ""
    latest_chart = json.dumps({"type": "bar", "labels": [x["subject"] for x in scored[-1]["subjects"]], "values": [x["pct"] for x in scored[-1]["subjects"]],
                               "unit": "%", "max": 100, "ref": 33, "refLabel": "Pass"}, default=float) if scored else ""

    courses = cls.courses.select_related("subject", "teacher") if cls else []
    rows = course_rows(student, courses) if cls else []
    done, total = sum(r["done"] for r in rows), sum(r["total"] for r in rows)
    quiz = [x["avg"] for x in student_summary(student, courses)] if cls else []
    quiz = [q for q in quiz if q is not None]
    profile = getattr(student, "student_profile", None)
    from nuggets.models import StudentNugget
    nug = list(StudentNugget.objects.filter(student=student, nugget__is_published=True, nugget__review="approved").select_related("nugget__course__subject").order_by("status", "-assigned_at")[:6])
    from fees import services as fee_services, views as fee_views
    fees = fee_services.summary(student) if fee_views.can_view(me, student) else None
    from datetime import timedelta

    from django.utils import timezone

    from attendance import services as att_services, views as att_views
    att = att_services.summary(student, timezone.localdate() - timedelta(days=30)) if att_views.can_view_student(me, student) else None
    return render(request, "organization/student_profile.html", {"nug": nug, "fees": fees, "att": att, 
        "student": student, "cls": cls, "profile": profile, "terms": list(reversed(terms)), "terms_asc": terms, "matrix": matrix, "kpi": kpi, "staff": staff,
        "trend_chart": trend_chart, "latest_chart": latest_chart, "rows": rows, "lesson_pct": round(done * 100 / total) if total else None,
        "quiz_avg": round(sum(quiz) / len(quiz), 1) if quiz else None, "guardians": student.parents.all() if (staff or me.pk == student.pk) else [],
        "can_message": me.pk != student.pk and can_chat(me, student), "is_self": me.pk == student.pk,
        "page": "record" if me.pk == student.pk else ("child" if me.is_parent else "students"), "active_child": student.pk,
    })


# ------------------------------------------------------------------ campus comparison & export
@perm("campuses.view")
def compare(request):
    import json

    from . import analytics

    rows = analytics.campus_stats(request.user)
    region = request.GET.get("region", "")
    if region.isdigit():
        rows = [r for r in rows if r["region"].pk == int(region)]
    if request.GET.get("format") == "csv":
        if not has_perm(request.user, "reports.export"):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        audit.record(request, "export.campus_compare", "campuses", f"{len(rows)} rows")
        return _csv("campus-comparison.csv",
                    ["Rank", "Region", "Campus", "Students", "Teachers", "Avg exam %", "Pass rate %", "At risk", "Nugget mastery %"],
                    [[r["rank"] or "", r["region"].name, r["campus"].name, r["students"], r["teachers"],
                      r["avg_pct"] if r["avg_pct"] is not None else "", r["pass_rate"] if r["pass_rate"] is not None else "",
                      r["at_risk"], r["mastery"] if r["mastery"] is not None else ""] for r in rows])
    scored = [r for r in rows if r["avg_pct"] is not None]
    chart = json.dumps({"type": "hbar", "labels": [r["campus"].name for r in scored], "values": [r["avg_pct"] for r in scored],
                        "unit": "%", "max": 100, "single": True, "title": "Average exam % by campus"}, default=float) if scored else ""
    return render(request, "organization/compare.html", {
        "rows": rows, "tot": analytics.totals(rows), "chart": chart, "page": "compare",
        "regions": Region.objects.filter(campuses__in=scope.campuses_for(request.user)).distinct(), "region": region,
        "can_export": has_perm(request.user, "reports.export"),
    })


def _csv(name, header, rows):
    import csv

    from django.http import HttpResponse
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    resp.write("﻿")
    w = csv.writer(resp)
    w.writerow(header)
    for r in rows:
        w.writerow(["'" + str(c) if isinstance(c, str) and c[:1] in "=+-@" else c for c in r])  # block CSV formula injection
    return resp


@perm("students.export")
def student_export(request):
    qs = student_queryset(request.GET, request.user).order_by("first_name", "username")
    audit.record(request, "export.students", "students", f"{qs.count()} rows")
    return _csv("students.csv", ["Admission no", "Name", "Username", "Email", "Phone", "Region", "Campus", "Active"],
                [[getattr(u.student_profile, "admission_no", "") if hasattr(u, "student_profile") else "", u.display_name, u.username, u.email, u.phone,
                  u.student_profile.campus.region.name if getattr(getattr(u, "student_profile", None), "campus", None) else "",
                  u.student_profile.campus.name if getattr(getattr(u, "student_profile", None), "campus", None) else "",
                  "yes" if u.is_active else "no"] for u in qs])
