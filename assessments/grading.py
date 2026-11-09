"""Auto-grading and grade helpers (pure functions + small queries)."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Answer, Assessment, Attempt, Question


def norm(s):
    return " ".join((s or "").lower().split())


def grade_answer(question, answer):
    """Set answer.points for auto-graded questions. Long answers stay None."""
    if question.kind in (Question.Kind.MCQ, Question.Kind.TF):
        ok = bool(answer.choice_id and answer.choice and answer.choice.is_correct)
        answer.points = question.points if ok else Decimal("0")
    elif question.kind == Question.Kind.SHORT:
        accepted = {norm(a) for a in question.accepted.split("|") if a.strip()}
        answer.points = question.points if norm(answer.text) in accepted and accepted else Decimal("0")
    else:
        answer.points = None
    return answer


def recompute(attempt):
    """Recalculate total/score/needs_review from the saved answers."""
    questions = list(attempt.assessment.questions.all())
    answers = {a.question_id: a for a in attempt.answers.all()}
    attempt.total = sum((q.points for q in questions), Decimal("0"))
    attempt.score = sum((a.points for a in answers.values() if a.points is not None), Decimal("0"))
    attempt.needs_review = any(q.kind == Question.Kind.LONG and (
        q.id not in answers or answers[q.id].points is None) for q in questions)
    attempt.save(update_fields=["total", "score", "needs_review"])
    return attempt


@transaction.atomic
def submit_attempt(attempt, post):
    """Save the posted answers (unless the time limit has passed), grade and close the attempt."""
    if attempt.submitted:
        return attempt
    accept = not attempt.expired
    for q in attempt.assessment.questions.prefetch_related("choices"):
        ans, _ = Answer.objects.get_or_create(attempt=attempt, question=q)
        if accept:
            key = f"q{q.id}"
            if q.kind in (Question.Kind.MCQ, Question.Kind.TF):
                cid = post.get(key)
                ans.choice = q.choices.filter(pk=cid).first() if cid and cid.isdigit() else None
            else:
                ans.text = (post.get(key) or "").strip()
        grade_answer(q, ans)
        ans.save()
    attempt.submitted_at = timezone.now()
    attempt.save(update_fields=["submitted_at"])
    _complete_quiz_items(attempt)
    return recompute(attempt)


def attempts_left(assessment, student):
    used = Attempt.objects.filter(assessment=assessment, student=student, submitted_at__isnull=False).count()
    return max(assessment.max_attempts - used, 0)


def best_attempt(assessment, student):
    """Best submitted attempt by percent (None if none)."""
    best = None
    for a in Attempt.objects.filter(assessment=assessment, student=student, submitted_at__isnull=False):
        if best is None or a.percent > best.percent:
            best = a
    return best


def letter(pct):
    """Letter grade for a percentage, from the school grade scale (exams.GradeBand)."""
    from exams.grading import grade_letter
    return grade_letter(pct)


def _old_letter(pct):
    if pct is None:
        return "—"
    for cut, g in ((90, "A+"), (80, "A"), (70, "B"), (60, "C"), (50, "D")):
        if pct >= cut:
            return g
    return "F"


def gradebook(course, students):
    """Rows for a course gradebook: per student → per assessment best % plus the average."""
    assessments = list(Assessment.objects.filter(course=course, is_published=True).order_by("created_at"))
    rows = []
    for s in students:
        cells, pcts = [], []
        for a in assessments:
            att = best_attempt(a, s)
            if att is None:
                cells.append({"assessment": a, "pct": None, "pending": False})
            else:
                cells.append({"assessment": a, "pct": att.percent, "pending": att.needs_review, "attempt": att})
                pcts.append(att.percent)
        avg = round(sum(pcts) / len(pcts), 1) if pcts else None
        rows.append({"student": s, "cells": cells, "avg": avg, "letter": letter(avg), "done": len(pcts)})
    return assessments, rows


def student_summary(student, courses):
    """Per-course results for the student/parent progress pages."""
    out = []
    for c in courses:
        items = []
        for a in Assessment.objects.filter(course=c, is_published=True).order_by("created_at"):
            att = best_attempt(a, student)
            items.append({"assessment": a, "attempt": att, "pct": att.percent if att else None})
        pcts = [i["pct"] for i in items if i["pct"] is not None]
        avg = round(sum(pcts) / len(pcts), 1) if pcts else None
        out.append({"course": c, "items": items, "avg": avg, "letter": letter(avg)})
    return out


def _complete_quiz_items(attempt):
    """Submitting a quiz completes the course item(s) that point to it."""
    from academics.models import Lesson, LessonProgress
    for lesson in Lesson.objects.filter(assessment_id=attempt.assessment_id):
        LessonProgress.objects.get_or_create(student=attempt.student, lesson=lesson)
