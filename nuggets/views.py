from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.templatetags.ui import subj_kind

from academics.models import Course, Enrollment, student_class
from academics.views import can_manage
from accounts.decorators import role_required
from exams.models import Exam

import logging

from . import engine, gamify, suggest, tutor
from .forms import NuggetForm
from .models import Nugget, StudentNugget

audit = logging.getLogger("audit")


def _staff(user):
    return user.is_super_admin or user.is_teacher


def _courses(user):
    qs = Course.objects.select_related("subject", "school_class")
    return qs if user.is_super_admin else qs.filter(teacher=user)


def _guard(user, nugget):
    if not (user.is_super_admin or (user.is_teacher and can_manage(user, nugget.course))):
        raise PermissionDenied


# ------------------------------------------------------------------ student
@login_required
def home(request):
    if _staff(request.user):
        return redirect("nuggets:manage")
    if not request.user.is_student:
        raise PermissionDenied
    rows = list(StudentNugget.objects.filter(student=request.user, nugget__is_published=True, nugget__review="approved")
                .select_related("nugget__course__subject").order_by("status", "-assigned_at"))
    due = [r for r in rows if r.due]
    todo = [r for r in rows if r.status == "assigned"]
    done = [r for r in rows if r.status == "done" and not r.due]
    StudentNugget.objects.filter(pk__in=[r.pk for r in todo], seen=False).update(seen=True)
    st = gamify.stat_for(request.user)
    return render(request, "nuggets/home.html", {
        "todo": todo, "due": due, "done": done, "page": "nuggets", "pass_pct": engine.PASS_PCT,
        "stat": st, "badges": gamify.badge_list(st), "all_badges": gamify.BADGES, "xp_in_level": st.xp % 100})


@login_required
@role_required("student")
@require_POST
def refresh(request):
    new = [r for r in engine.plan_for_student(request.user) if r.nugget.live]
    messages.success(request, f"{len(new)} new nugget{'s' if len(new) != 1 else ''} added for your weak areas." if new
                     else "Nothing new right now — you are on track, or your open nuggets already cover your weak areas.")
    return redirect("nuggets:home")


def _can_open(user, n):
    if user.is_super_admin or (user.is_teacher and can_manage(user, n.course)):
        return True
    if user.is_student:
        return n.live and (StudentNugget.objects.filter(student=user, nugget=n).exists() or student_class(user) == n.course.school_class)
    return False


@login_required
def play(request, pk):
    n = get_object_or_404(Nugget.objects.select_related("course__subject", "course__school_class"), pk=pk)
    if not _can_open(request.user, n):
        raise PermissionDenied
    row = StudentNugget.objects.filter(student=request.user, nugget=n).first() if request.user.is_student else None
    if row and not row.seen:
        row.seen = True
        row.save(update_fields=["seen"])
    return render(request, "nuggets/play.html", {"n": n, "row": row, "preview": not request.user.is_student, "page": "nuggets", "pass_pct": engine.PASS_PCT,
                                                 "missed": (row.missed if row else []), "revision": bool(row and row.due)})


@login_required
@require_POST
def check(request, pk):
    n = get_object_or_404(Nugget, pk=pk)
    if not _can_open(request.user, n):
        raise PermissionDenied
    correct, total, results = engine.grade_check(n, request.POST)
    pct = round(correct * 100 / total, 1) if total else 100.0
    out = {"correct": correct, "total": total, "pct": pct, "results": results, "pass": pct >= engine.PASS_PCT}
    if request.user.is_student:
        row, extras = engine.record(request.user, n, pct, engine.missed_of(results))
        out.update(status=row.status, best=float(row.score or 0), **extras)
    return JsonResponse(out)


@login_required
@require_POST
def tutor_view(request, pk):
    """Ask the AI tutor about this nugget. Grounded in the lesson; rate-limited per user."""
    n = get_object_or_404(Nugget.objects.select_related("course__subject", "course__school_class"), pk=pk)
    if not _can_open(request.user, n):
        raise PermissionDenied
    msg = (request.POST.get("message") or "").strip()[:500]
    if not msg:
        return JsonResponse({"error": "Type a question."}, status=400)
    key = f"tutor:{request.user.pk}"
    used = cache.get(key, 0)
    if used >= tutor.HOURLY_LIMIT:
        return JsonResponse({"error": "You have asked a lot of questions this hour. Take a short break, or ask your teacher."}, status=429)
    cache.set(key, used + 1, 3600)
    history = []
    try:
        import json
        history = json.loads(request.POST.get("history") or "[]")[-6:]
    except ValueError:
        pass
    answer, source = tutor.ask(n, msg, history)
    return JsonResponse({"answer": answer, "source": source, "left": tutor.HOURLY_LIMIT - used - 1})


# ------------------------------------------------------------------ teacher / admin
@login_required
def manage(request):
    if not _staff(request.user):
        raise PermissionDenied
    courses = _courses(request.user)
    cid = request.GET.get("course")
    qs = Nugget.objects.filter(course__in=courses).select_related("course__subject", "course__school_class")
    pending_n = qs.filter(review="pending").count()
    only_pending = request.GET.get("review") == "pending"
    if only_pending:
        qs = qs.filter(review="pending")
    if cid and cid.isdigit():
        qs = qs.filter(course_id=int(cid))
    items = list(qs)
    counts = {}
    for sn in StudentNugget.objects.filter(nugget__in=items).values_list("nugget_id", "status"):
        c = counts.setdefault(sn[0], [0, 0])
        c[0] += 1
        c[1] += sn[1] == "done"
    for i in items:
        i.n_assigned, i.n_done = counts.get(i.id, [0, 0])
    classes = {c.school_class_id for c in courses}
    exams = Exam.objects.filter(school_class_id__in=classes).select_related("school_class").order_by("-id")[:30]
    return render(request, "nuggets/manage.html", {"items": items, "courses": courses, "cid": int(cid) if cid and cid.isdigit() else None,
                                                   "exams": exams, "page": "nuggets", "pending_n": pending_n, "only_pending": only_pending})


@login_required
def nugget_form(request, pk=None):
    if not _staff(request.user):
        raise PermissionDenied
    obj = get_object_or_404(Nugget, pk=pk) if pk else None
    if obj:
        _guard(request.user, obj)
    form = NuggetForm(request.POST or None, instance=obj, courses=_courses(request.user))
    if request.method == "POST" and form.is_valid():
        n = form.save(commit=False)
        if not obj:
            n.created_by = request.user
            n.source = Nugget.Source.MANUAL
        was_pending = bool(obj and obj.review == "pending")
        n.save()
        if was_pending:   # a teacher who edits and saves a draft has reviewed it
            engine.approve(n, request.user)
        messages.success(request, "Nugget saved" + (" and approved — students can see it now." if was_pending else "."))
        return redirect("nuggets:stats", pk=n.pk)
    kinds = {c.pk: subj_kind(c.subject.name) for c in _courses(request.user)}
    return render(request, "nuggets/form.html", {"form": form, "obj": obj, "kinds": kinds, "page": "nuggets"})


@login_required
@require_POST
def nugget_delete(request, pk):
    n = get_object_or_404(Nugget, pk=pk)
    _guard(request.user, n)
    n.delete()
    messages.success(request, "Nugget deleted.")
    return redirect("nuggets:manage")


@login_required
@require_POST
def generate(request):
    if not _staff(request.user):
        raise PermissionDenied
    course = get_object_or_404(_courses(request.user), pk=request.POST.get("course") or 0)
    topic = (request.POST.get("topic") or "").strip()[:120]
    if not topic:
        messages.error(request, "Type the topic first.")
        return redirect("nuggets:manage")
    n = engine.generate_nugget(course, topic, created_by=request.user)
    messages.success(request, f"Created “{n.title}” ({n.get_source_display()}). Review it, then send it to the class.")
    return redirect("nuggets:edit", pk=n.pk)


@login_required
@require_POST
def auto_exam(request):
    if not _staff(request.user):
        raise PermissionDenied
    exam = get_object_or_404(Exam, pk=request.POST.get("exam") or 0)
    if not request.user.is_super_admin and not Course.objects.filter(teacher=request.user, school_class=exam.school_class).exists():
        raise PermissionDenied
    s = engine.assign_for_exam(exam)
    messages.success(request, f"{s['assigned']} nuggets sent to {s['students']} students for weak subjects in {exam.name}"
                              + (f" ({s['created']} new nuggets created)." if s["created"] else "."))
    return redirect("nuggets:manage")


@login_required
def stats(request, pk):
    n = get_object_or_404(Nugget.objects.select_related("course__subject", "course__school_class"), pk=pk)
    _guard(request.user, n)
    rows = StudentNugget.objects.filter(nugget=n).select_related("student").order_by("status", "student__first_name")
    class_size = Enrollment.objects.filter(school_class=n.course.school_class).count()
    return render(request, "nuggets/stats.html", {"n": n, "rows": rows, "class_size": class_size, "page": "nuggets"})


@login_required
@require_POST
def assign(request, pk):
    n = get_object_or_404(Nugget, pk=pk)
    _guard(request.user, n)
    k = engine.assign_to_class(n)
    messages.success(request, f"Sent to {k} student{'s' if k != 1 else ''}." if k else "Everyone in the class already has this nugget.")
    return redirect("nuggets:stats", pk=n.pk)


@login_required
@require_POST
def suggest_view(request):
    """AI coach: feedback + ready-to-apply improvements for the draft on screen."""
    if not _staff(request.user):
        raise PermissionDenied
    course = get_object_or_404(_courses(request.user), pk=request.POST.get("course") or 0)
    from .forms import parse_cards, parse_questions
    qs, _errors = parse_questions(request.POST.get("questions_text", ""))
    d = {"subject": course.subject.name, "class_name": course.school_class.name, "topic": request.POST.get("topic", "")[:120],
         "title": request.POST.get("title", "")[:200], "explanation": request.POST.get("explanation", "")[:4000],
         "key_points": request.POST.get("key_points", "")[:2000], "video_url": request.POST.get("video_url", "")[:300],
         "cards": parse_cards(request.POST.get("cards_text", "")), "questions": qs}
    result, source, error = suggest.review(d)
    result["extra_question_lines"] = [suggest.question_line(q) for q in result.get("extra_questions", [])]
    result["extra_card_lines"] = [" | ".join(c) for c in result.get("extra_cards", [])]
    return JsonResponse({**result, "source": source, "error": error})


@login_required
@require_POST
def approve(request, pk):
    n = get_object_or_404(Nugget, pk=pk)
    _guard(request.user, n)
    engine.approve(n, request.user)
    audit.info("nugget approved id=%s by=%s", n.pk, request.user.username)
    from core import audit as _a
    _a.record(request, "nugget.approve", n.title, f"id={n.pk}")
    messages.success(request, f"“{n.title}” approved. {n.assignments.count()} student(s) were notified.")
    return redirect(request.POST.get("next") if (request.POST.get("next") or "").startswith("/") else "nuggets:manage")


@login_required
@require_POST
def reject(request, pk):
    n = get_object_or_404(Nugget, pk=pk)
    _guard(request.user, n)
    title = n.title
    audit.info("nugget rejected id=%s by=%s", n.pk, request.user.username)
    from core import audit as _a
    _a.record(request, "nugget.reject", n.title, f"id={n.pk}")
    n.delete()   # the draft and its (hidden) assignments are removed; a better one can be generated later
    messages.success(request, f"Draft “{title}” rejected and removed.")
    return redirect("nuggets:manage")


@login_required
def insights(request):
    """Which topics is the class struggling with? Heatmap of students × nuggets."""
    if not _staff(request.user):
        raise PermissionDenied
    courses = list(_courses(request.user))
    cid = request.GET.get("course")
    course = next((c for c in courses if str(c.pk) == cid), courses[0] if courses else None)
    ctx = {"courses": courses, "course": course, "page": "nuggets"}
    if course:
        nuggets = list(Nugget.objects.filter(course=course, review="approved", is_published=True).order_by("id"))
        students = [e.student for e in Enrollment.objects.filter(school_class=course.school_class).select_related("student").order_by("student__first_name", "student__username")]
        rows = {(r.student_id, r.nugget_id): r for r in StudentNugget.objects.filter(nugget__in=nugget_ids(nuggets))}
        topics = []
        for n in nuggets:
            rs = [rows[(s.id, n.id)] for s in students if (s.id, n.id) in rows]
            scored = [float(r.score) for r in rs if r.score is not None]
            topics.append({"nugget": n, "sent": len(rs), "mastered": sum(r.status == "done" for r in rs),
                           "avg": round(sum(scored) / len(scored), 1) if scored else None,
                           "struggling": sum(1 for r in rs if r.attempts >= 2 and r.status != "done")})
        topics_ranked = sorted([t for t in topics if t["sent"]], key=lambda t: (t["avg"] is None, t["avg"] if t["avg"] is not None else 101))
        grid = [{"student": s, "cells": [rows.get((s.id, n.id)) for n in nuggets],
                 "mastered": sum(1 for n in nuggets if rows.get((s.id, n.id)) and rows[(s.id, n.id)].status == "done")} for s in students]
        ctx.update(nuggets=nuggets, topics=topics_ranked, grid=grid)
        if request.GET.get("csv"):
            import csv

            from django.http import HttpResponse
            resp = HttpResponse(content_type="text/csv")
            resp["Content-Disposition"] = f'attachment; filename="nuggets-{course.pk}.csv"'
            w = csv.writer(resp)
            w.writerow(["Student"] + [n.title for n in nuggets])
            for g in grid:
                w.writerow([g["student"].display_name] + [("" if c is None else (f"{c.score}%" if c.score is not None else "sent")) for c in g["cells"]])
            return resp
    return render(request, "nuggets/insights.html", ctx)


def nugget_ids(nuggets):
    return [n.id for n in nuggets]
