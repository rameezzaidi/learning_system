import csv

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from accounts.models import User
from accounts.rbac import perm_required
from core import audit

from . import services


def _csv_safe(v):
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v


@login_required
def dna(request, pk):
    st = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    if not services.can_view_profile(request.user, st):
        raise PermissionDenied
    return render(request, "insights/dna.html", {"p": services.learning_profile(st), "can_remark": not (request.user.is_student or request.user.is_parent), "page": "child" if request.user.is_parent else "students"})


@login_required
@perm_required("bank.manage")
def lesson_plan(request):
    from bank.services import courses_for
    courses = list(courses_for(request.user))
    plan = None
    form = {"course": "", "topic": "", "minutes": 40, "level": "mixed"}
    if request.method == "POST":
        form.update({k: request.POST.get(k, "") for k in form})
        c = next((x for x in courses if str(x.pk) == form["course"]), None)
        topic = form["topic"].strip()[:160]
        try:
            minutes = max(20, min(int(form["minutes"]), 120))
        except ValueError:
            minutes = 40
        form["minutes"] = minutes
        if c and topic:
            plan = services.lesson_plan(c.subject.name, str(c.school_class), topic, minutes, form["level"] if form["level"] in ("support", "mixed", "advanced") else "mixed")
            plan["meta"] = f"{c.subject.name} · {c.school_class} · {topic} · {minutes} min"
            audit.record(request, "lessonplan", str(c), topic)
    return render(request, "insights/lesson_plan.html", {"courses": courses, "plan": plan, "form": form, "page": "lessonplan"})


@login_required
@perm_required("bi.view")
def executive(request):
    rows = services.executive(request.user)
    if request.GET.get("format") == "csv":
        audit.record(request, "export.executive", "campus summary")
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="executive-summary.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Campus", "Region", "Students", "Teachers", "Avg exam %", "Pass rate %", "Attendance % (30d)", "Billed (this month)", "Collected", "Collection %", "Open alerts"])
        for r in rows:
            w.writerow([_csv_safe(r["campus"].name), _csv_safe(r["region"].name), r["students"], r["teachers"], r["avg_pct"] if r["avg_pct"] is not None else "",
                        r["pass_rate"] if r["pass_rate"] is not None else "", r["attendance"] if r["attendance"] is not None else "", r["billed"], r["collected"],
                        r["collection"] if r["collection"] is not None else "", r["alerts"]])
        return resp
    tot = {"students": sum(r["students"] for r in rows), "alerts": sum(r["alerts"] for r in rows), "billed": sum(r["billed"] for r in rows), "collected": sum(r["collected"] for r in rows)}
    tot["collection"] = round(float(tot["collected"]) * 100 / float(tot["billed"]), 1) if tot["billed"] else None
    return render(request, "insights/executive.html", {"rows": rows, "tot": tot, "page": "executive"})
