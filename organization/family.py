"""Parent portal: one plain-language overview per child. Published results and approved nuggets only."""
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User

AT_RISK = 50.0


def _terms(student):
    from exams import grading, insights
    from exams.models import Exam
    exams = Exam.objects.filter(is_published=True, papers__marks__student=student).select_related("school_class").distinct()
    exams = sorted(exams, key=lambda e: (e.start_date is None, e.start_date or e.created_at.date(), e.id))
    terms = []
    for e in exams:
        res = grading.compute(e)
        row = grading.row_for(res, student.id)
        if not row or row["pct"] is None:
            continue
        ins = insights.student_insights(res, row, None)
        terms.append({"exam": e, "pct": ins["overall_pct"], "grade": ins["grade"], "rank": ins["rank"], "n_ranked": ins["n_ranked"],
                      "result": ins["result"], "subjects": ins["subjects"]})
    return terms


def snapshot(student):
    from academics.models import course_rows, student_class
    from assessments.grading import student_summary
    from nuggets.models import LearnerStat, StudentNugget

    terms = _terms(student)
    latest = terms[-1] if terms else None
    prev = terms[-2] if len(terms) > 1 else None
    delta = round(latest["pct"] - prev["pct"], 1) if latest and prev else None
    weak = [s for s in (latest["subjects"] if latest else []) if s["status"] == "weak"]
    strong = [s for s in (latest["subjects"] if latest else []) if s["status"] == "strong"]

    cls = student_class(student)
    courses = list(cls.courses.select_related("subject", "teacher")) if cls else []
    rows = course_rows(student, courses)
    done, total = sum(r["done"] for r in rows), sum(r["total"] for r in rows)
    quiz = [x["avg"] for x in student_summary(student, courses) if x["avg"] is not None] if courses else []

    nugs = list(StudentNugget.objects.filter(student=student, nugget__is_published=True, nugget__review="approved")
                .select_related("nugget__course__subject").order_by("status", "-assigned_at"))
    n_done = sum(1 for n in nugs if n.status == "done")
    open_n = [n for n in nugs if n.status != "done"]
    stat = LearnerStat.objects.filter(student=student).first()

    tips = []
    for s in weak[:3]:
        tips.append(f"{s['subject']}: {s['pct']}% — practise 15–20 minutes, 4 days a week, and ask the child to explain one solved question aloud.")
    if open_n:
        tips.append(f"{len(open_n)} short lesson{'s' if len(open_n) != 1 else ''} (nuggets) are waiting — about 5 minutes each. Start with “{open_n[0].nugget.title}”.")
    if delta is not None and delta <= -5:
        tips.append(f"Overall marks dropped {abs(delta)} points since the last exam. A short chat with the class teacher can help find the cause.")
    if delta is not None and delta >= 5:
        tips.append(f"Overall marks improved {delta} points since the last exam — worth praising the effort.")
    if not tips and latest:
        tips.append("Doing well. Keep a steady routine: reading daily and a short revision session each weekend.")

    return {
        "student": student, "cls": cls, "terms": terms, "latest": latest, "delta": delta, "weak": weak, "strong": strong,
        "avg": round(sum(t["pct"] for t in terms) / len(terms), 1) if terms else None,
        "at_risk": bool(latest and latest["pct"] < AT_RISK), "lesson_pct": round(done * 100 / total) if total else None,
        "lessons": (done, total), "quiz_avg": round(sum(quiz) / len(quiz), 1) if quiz else None, "rows": rows,
        "nug_total": len(nugs), "nug_done": n_done, "nug_open": open_n[:5], "stat": stat,
        "mastery": round(n_done * 100 / len(nugs)) if nugs else None, "tips": tips,
        "teachers": sorted({c.teacher for c in courses if c.teacher}, key=lambda u: u.display_name),
        "trend": json.dumps({"type": "line", "labels": [t["exam"].name[:14] for t in terms], "values": [t["pct"] for t in terms],
                             "unit": "%", "max": 100}, default=float) if terms else "",
        "subj_chart": json.dumps({"type": "bar", "labels": [s["subject"] for s in latest["subjects"]], "values": [s["pct"] for s in latest["subjects"]],
                                  "unit": "%", "max": 100, "ref": 33, "refLabel": "Pass"}, default=float) if latest and latest["subjects"] else "",
    }


@login_required
def child_overview(request, pk):
    me = request.user
    if not me.is_parent:
        raise PermissionDenied
    kids = list(me.children.all())
    child = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    if child not in kids:
        raise PermissionDenied
    from chat.permissions import can_chat
    snap = snapshot(child)
    from fees import services as fee_services
    snap["fees"] = fee_services.summary(child)
    from datetime import timedelta

    from django.utils import timezone

    from attendance import services as att_services
    snap["attendance"] = att_services.summary(child, timezone.localdate() - timedelta(days=30))
    snap["teachers"] = [(t, can_chat(me, t)) for t in snap["teachers"]]
    return render(request, "organization/family.html", {"s": snap, "kids": kids, "child": child, "page": "child", "active_child": child.pk})


@login_required
def family_home(request):
    kids = list(request.user.children.all()) if request.user.is_parent else []
    if not request.user.is_parent:
        raise PermissionDenied
    if kids:
        return redirect("organization:family", pk=kids[0].pk)
    return render(request, "organization/family.html", {"s": None, "kids": [], "child": None, "page": "child"})
