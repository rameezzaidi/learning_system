import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from academics.models import Course, Enrollment, student_class
from academics.views import can_manage
from accounts.decorators import role_required
from accounts.models import User

from . import grading
from .forms import AssessmentForm, QuestionForm
from .models import Answer, Assessment, Attempt, Question


# ---------- access ----------

def _manage_assessment(user, assessment):
    if not can_manage(user, assessment.course):
        raise PermissionDenied


def _student_can_see(user, assessment):
    return (user.is_student and assessment.is_published and Enrollment.objects.filter(
        student=user, school_class_id=assessment.course.school_class_id).exists())


def _managed_courses(user):
    qs = Course.objects.select_related("subject", "school_class")
    return qs if user.is_super_admin else qs.filter(teacher=user)


# ---------- list ----------

@login_required
def assessment_list(request):
    user = request.user
    if user.is_super_admin or user.is_teacher:
        courses = _managed_courses(user)
        items = Assessment.objects.filter(course__in=courses).select_related("course__subject", "course__school_class")
        return render(request, "assessments/list_manage.html", {
            "items": items, "courses": courses, "page": "assessments"})
    if not user.is_student:
        raise PermissionDenied
    cls = student_class(user)
    now = timezone.now()
    rows = []
    if cls:
        for a in Assessment.objects.filter(course__school_class=cls, is_published=True).select_related("course__subject"):
            best = grading.best_attempt(a, user)
            open_attempt = Attempt.objects.filter(assessment=a, student=user, submitted_at__isnull=True).first()
            left = grading.attempts_left(a, user)
            closed = a.is_past_due
            state = "done" if best and (left == 0 or closed) else "closed" if closed and not best else "open"
            rows.append({"a": a, "best": best, "left": left, "state": state, "in_progress": open_attempt,
                         "can_start": left > 0 and not closed})
    return render(request, "assessments/list_student.html", {"rows": rows, "page": "assessments", "now": now})


# ---------- teacher: assessments ----------

@login_required
def assessment_form(request, course_pk=None, pk=None):
    obj = get_object_or_404(Assessment, pk=pk) if pk else None
    course = obj.course if obj else get_object_or_404(Course, pk=course_pk)
    if not can_manage(request.user, course):
        raise PermissionDenied
    form = AssessmentForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        a = form.save(commit=False)
        a.course = course
        a.save()
        messages.success(request, "Assessment saved. Now add questions.")
        return redirect("assessments:detail", pk=a.pk)
    return render(request, "assessments/form.html", {
        "form": form, "title": "Edit assessment" if obj else f"New assessment · {course}", "page": "assessments",
        "back": "assessments:detail" if obj else "assessments:list", "back_arg": obj.pk if obj else None})


@login_required
def assessment_detail(request, pk):
    a = get_object_or_404(Assessment.objects.select_related("course__subject", "course__school_class"), pk=pk)
    _manage_assessment(request.user, a)
    questions = a.questions.prefetch_related("choices")
    attempts = a.attempts.filter(submitted_at__isnull=False)
    return render(request, "assessments/detail.html", {
        "a": a, "questions": questions, "n_attempts": attempts.count(),
        "pending": attempts.filter(needs_review=True).count(), "page": "assessments"})


@login_required
@require_POST
def assessment_toggle(request, pk):
    a = get_object_or_404(Assessment, pk=pk)
    _manage_assessment(request.user, a)
    if not a.is_published and not a.questions.exists():
        messages.error(request, "Add at least one question before publishing.")
    else:
        a.is_published = not a.is_published
        a.save(update_fields=["is_published"])
        messages.success(request, "Published — students can see it now." if a.is_published else "Moved back to draft.")
    return redirect("assessments:detail", pk=a.pk)


@login_required
@require_POST
def assessment_delete(request, pk):
    a = get_object_or_404(Assessment, pk=pk)
    _manage_assessment(request.user, a)
    course = a.course
    a.delete()
    messages.success(request, "Assessment deleted.")
    return redirect("assessments:list")


# ---------- teacher: questions ----------

@login_required
def question_form(request, assessment_pk=None, pk=None):
    obj = get_object_or_404(Question, pk=pk) if pk else None
    a = obj.assessment if obj else get_object_or_404(Assessment, pk=assessment_pk)
    _manage_assessment(request.user, a)
    form = QuestionForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save_with_choices(a)
        messages.success(request, "Question saved.")
        if "add_another" in request.POST:
            return redirect("assessments:question_create", assessment_pk=a.pk)
        return redirect("assessments:detail", pk=a.pk)
    return render(request, "assessments/question_form.html", {
        "form": form, "a": a, "title": "Edit question" if obj else "Add question", "page": "assessments"})


@login_required
@require_POST
def question_delete(request, pk):
    q = get_object_or_404(Question, pk=pk)
    _manage_assessment(request.user, q.assessment)
    a = q.assessment
    q.delete()
    messages.success(request, "Question deleted.")
    return redirect("assessments:detail", pk=a.pk)


# ---------- teacher: results & marking ----------

@login_required
def results(request, pk):
    a = get_object_or_404(Assessment.objects.select_related("course__subject", "course__school_class"), pk=pk)
    _manage_assessment(request.user, a)
    attempts = a.attempts.filter(submitted_at__isnull=False).select_related("student").order_by("student__first_name", "-started_at")
    return render(request, "assessments/results.html", {"a": a, "attempts": attempts, "page": "assessments"})


@login_required
def attempt_review(request, pk):
    att = get_object_or_404(Attempt.objects.select_related("assessment__course", "student"), pk=pk)
    _manage_assessment(request.user, att.assessment)
    if not att.submitted:
        raise PermissionDenied
    answers = {x.question_id: x for x in att.answers.all()}
    questions = list(att.assessment.questions.prefetch_related("choices"))
    if request.method == "POST":
        for q in questions:
            ans, _ = Answer.objects.get_or_create(attempt=att, question=q)
            raw = request.POST.get(f"pts{q.id}", "").strip()
            if raw != "":
                try:
                    pts = max(min(float(raw), float(q.points)), 0)
                except ValueError:
                    continue
                ans.points = pts
            ans.feedback = request.POST.get(f"fb{q.id}", "").strip()[:500]
            ans.save()
        grading.recompute(att)
        messages.success(request, "Marks saved.")
        return redirect("assessments:results", pk=att.assessment_id)
    rows = [{"q": q, "ans": answers.get(q.id)} for q in questions]
    return render(request, "assessments/review.html", {"att": att, "rows": rows, "page": "assessments"})


# ---------- student ----------

@login_required
@require_POST
def start(request, pk):
    a = get_object_or_404(Assessment, pk=pk)
    if not _student_can_see(request.user, a):
        raise PermissionDenied
    open_attempt = Attempt.objects.filter(assessment=a, student=request.user, submitted_at__isnull=True).first()
    if open_attempt and not open_attempt.expired:
        return redirect("assessments:take", pk=open_attempt.pk)
    if open_attempt:  # timed out and abandoned → close it
        grading.submit_attempt(open_attempt, {})
    if a.is_past_due:
        messages.error(request, "The deadline has passed.")
        return redirect("assessments:list")
    if grading.attempts_left(a, request.user) <= 0:
        messages.error(request, "No attempts left.")
        return redirect("assessments:list")
    att = Attempt.objects.create(assessment=a, student=request.user, total=a.total_points)
    return redirect("assessments:take", pk=att.pk)


@login_required
def take(request, pk):
    att = get_object_or_404(Attempt.objects.select_related("assessment__course"), pk=pk, student=request.user)
    a = att.assessment
    if att.submitted:
        return redirect("assessments:result", pk=att.pk)
    if request.method == "POST":
        grading.submit_attempt(att, request.POST)
        try:
            from nuggets.engine import assign_after_attempt
            assign_after_attempt(att)
        except Exception:
            pass
        messages.success(request, "Submitted!" + (" Your teacher will mark the written answers." if att.needs_review else ""))
        return redirect("assessments:result", pk=att.pk)
    if att.expired:
        grading.submit_attempt(att, {})
        messages.error(request, "Time was up — the attempt was closed.")
        return redirect("assessments:result", pk=att.pk)
    deadline = att.deadline
    seconds = max(int((deadline - timezone.now()).total_seconds()), 0) if deadline else None
    return render(request, "assessments/take.html", {
        "att": att, "a": a, "questions": a.questions.prefetch_related("choices"), "seconds": seconds,
        "page": "assessments"})


@login_required
def result(request, pk):
    att = get_object_or_404(Attempt.objects.select_related("assessment__course__subject", "student"), pk=pk)
    user = request.user
    if not (att.student_id == user.id or can_manage(user, att.assessment.course)
            or (user.is_parent and user.children.filter(pk=att.student_id).exists())):
        raise PermissionDenied
    if not att.submitted:
        return redirect("assessments:take", pk=att.pk) if att.student_id == user.id else redirect("assessments:list")
    answers = {x.question_id: x for x in att.answers.all()}
    reveal = att.assessment.show_answers or can_manage(user, att.assessment.course)
    rows = [{"q": q, "ans": answers.get(q.id)} for q in att.assessment.questions.prefetch_related("choices")]
    return render(request, "assessments/result.html", {
        "att": att, "a": att.assessment, "rows": rows, "reveal": reveal, "grade": grading.letter(att.percent),
        "page": "assessments"})


@login_required
@role_required("student")
def my_progress(request):
    cls = student_class(request.user)
    courses = Course.objects.filter(school_class=cls).select_related("subject", "teacher") if cls else Course.objects.none()
    from academics.models import progress_for
    summary = grading.student_summary(request.user, courses)
    for s in summary:
        s["lessons"] = progress_for(request.user, s["course"])
    avgs = [s["avg"] for s in summary if s["avg"] is not None]
    overall = round(sum(avgs) / len(avgs), 1) if avgs else None
    return render(request, "assessments/progress.html", {
        "summary": summary, "overall": overall, "overall_letter": grading.letter(overall), "cls": cls, "page": "progress"})


# ---------- gradebook ----------

def _gradebook_ctx(request, course_pk):
    course = get_object_or_404(Course.objects.select_related("subject", "school_class"), pk=course_pk)
    if not can_manage(request.user, course):
        raise PermissionDenied
    students = User.objects.filter(enrollment__school_class=course.school_class).order_by("first_name", "username")
    assessments, rows = grading.gradebook(course, students)
    return course, assessments, rows


@login_required
def gradebook(request, course_pk):
    course, assessments, rows = _gradebook_ctx(request, course_pk)
    avgs = [r["avg"] for r in rows if r["avg"] is not None]
    return render(request, "assessments/gradebook.html", {
        "course": course, "assessments": assessments, "rows": rows, "page": "gradebook",
        "class_avg": round(sum(avgs) / len(avgs), 1) if avgs else None})


@login_required
def gradebook_csv(request, course_pk):
    course, assessments, rows = _gradebook_ctx(request, course_pk)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="gradebook-{course.pk}.csv"'
    resp.write("﻿")
    w = csv.writer(resp)
    w.writerow(["Student", *[a.title for a in assessments], "Average %", "Grade"])
    for r in rows:
        w.writerow([r["student"].display_name, *["" if c["pct"] is None else c["pct"] for c in r["cells"]],
                    "" if r["avg"] is None else r["avg"], r["letter"]])
    return resp


@login_required
def gradebook_index(request):
    """Teacher/admin: pick a course to open its gradebook."""
    if not (request.user.is_teacher or request.user.is_super_admin):
        raise PermissionDenied
    return render(request, "assessments/gradebook_index.html", {"courses": _managed_courses(request.user), "page": "gradebook"})
