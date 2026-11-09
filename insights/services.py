from datetime import timedelta

from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import User
from accounts.rbac import has_perm
from core import scope

STRONG, WEAK = 70, 50


# ------------------------------------------------------------------ learning profile
def can_view_profile(user, student):
    from academics.models import Course, student_class
    if user.is_super_admin or user.pk == student.pk:
        return True
    if user.is_parent:
        return user.children.filter(pk=student.pk).exists()
    if user.is_management:
        return scope.can_see_student(user, student)
    if user.is_teacher:
        cls = student_class(student)
        return bool(cls) and Course.objects.filter(teacher=user, school_class=cls).exists()
    return False


def learning_profile(student):
    """Objective picture from what the student has actually done. Not a personality label."""
    from academics.models import progress_for, student_class
    from assessments.grading import student_summary
    from attendance.services import summary as att_summary
    from exams import grading
    from exams.models import Exam
    from nuggets.models import StudentNugget
    cls = student_class(student)
    subjects = {}
    if cls:
        courses = list(cls.courses.select_related("subject"))
        for x in student_summary(student, courses):
            prog = progress_for(student, x["course"])
            subjects[x["course"].subject.name] = {"quiz": x["avg"], "exam": None, "lessons": prog["pct"], "lessons_done": prog["done"], "lessons_total": prog["total"]}
        exam = Exam.objects.filter(school_class=cls, is_published=True).order_by("-start_date", "-id").first()
        exam_name = exam.name if exam else None
        if exam:
            res = grading.compute(exam)
            row = grading.row_for(res, student.id)
            for cell in (row["cells"] if row else []):
                name = cell["paper"].course.subject.name
                if name in subjects and cell["entered"] and not cell["absent"]:
                    subjects[name]["exam"] = float(cell["pct"])
    else:
        exam_name = None
    rows = []
    for name, d in subjects.items():
        vals = [v for v in (d["quiz"], d["exam"]) if v is not None]
        score = round(sum(vals) / len(vals), 1) if vals else None
        level = None if score is None else ("strong" if score >= STRONG else "weak" if score < WEAK else "steady")
        rows.append({"subject": name, "score": score, "level": level, **d})
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    att = att_summary(student, timezone.localdate() - timedelta(days=30))
    nug = list(StudentNugget.objects.filter(student=student, nugget__is_published=True, nugget__review="approved").values_list("status", flat=True))
    mastered = sum(1 for s in nug if s == "done")
    scored = [r for r in rows if r["score"] is not None]
    strengths, focus = [r["subject"] for r in scored if r["level"] == "strong"], [r["subject"] for r in scored if r["level"] == "weak"]
    lessons_total = sum(r["lessons_total"] for r in rows)
    lessons_done = sum(r["lessons_done"] for r in rows)
    steps = []
    for s in focus[:3]:
        steps.append(f"Give extra practice in {s}: short daily revision and a quick re-check in two weeks.")
    if att["pct"] is not None and att["pct"] < 80:
        steps.append(f"Attendance is {att['pct']}%; every missed day costs lessons. Talk to the family about regular attendance.")
    if lessons_total and lessons_done * 100 / lessons_total < 50:
        steps.append("Less than half of the published lessons are done. Encourage steady progress through the course material.")
    if len(nug) and mastered * 100 / len(nug) < 50:
        steps.append("Several learning nuggets are not mastered yet. Retry them: spaced repetition fixes weak spots.")
    if strengths and not focus:
        steps.append(f"Doing well. Extend {strengths[0]} with harder questions to keep the student challenged.")
    if not steps:
        steps.append("Not enough results yet to suggest next steps. More quizzes and exams will sharpen this profile.")
    remark = _remark(student, strengths, focus, att, scored)
    return {"student": student, "cls": cls, "rows": rows, "att": att, "exam_name": exam_name, "nuggets": {"total": len(nug), "mastered": mastered},
            "lessons": {"done": lessons_done, "total": lessons_total}, "strengths": strengths, "focus": focus, "steps": steps, "remark": remark}


def _remark(student, strengths, focus, att, scored):
    name = student.first_name or student.username
    if not scored:
        return f"{name} does not have enough graded work yet for a remark."
    parts = []
    if strengths:
        parts.append(f"{name} is doing well in {', '.join(strengths[:3])}.")
    if focus:
        parts.append(f"More support is needed in {', '.join(focus[:3])}.")
    if not strengths and not focus:
        parts.append(f"{name} is making steady progress across subjects.")
    if att["pct"] is not None:
        parts.append(f"Attendance over the last 30 days is {att['pct']}%.")
    return " ".join(parts)


# ------------------------------------------------------------------ lesson planner
PLAN_KEYS = ("objectives", "starter", "main", "check", "differentiation", "homework", "resources")


def rule_plan(subject, topic, minutes, level):
    m = max(int(minutes or 40), 20)
    starter, check, close = max(round(m * 0.12), 4), max(round(m * 0.15), 5), max(round(m * 0.08), 3)
    main = max(m - starter - check - close, 8)
    return {
        "objectives": [f"Explain the key ideas of {topic} in their own words.", f"Apply {topic} to solve at least three {subject} problems.", "Identify and correct a common mistake."],
        "starter": f"({starter} min) Recall question or short quiz on the previous lesson, then show one real-life example linked to {topic}.",
        "main": [f"({main // 2} min) Teach: introduce {topic} with a worked example, thinking aloud.",
                 f"({main - main // 2} min) Guided practice in pairs, then independent practice at {level} level; teacher circulates and checks."],
        "check": f"({check} min) Exit ticket: 3 questions on {topic}; students self-mark against the model answers.",
        "differentiation": ["Support: sentence starters, a worked example to copy, fewer questions.", "Stretch: an open-ended problem that combines this topic with an earlier one."],
        "homework": f"Five practice questions on {topic} plus one question: 'What is still unclear?'",
        "resources": [f"{subject} textbook chapter on {topic}", "Whiteboard / slides with worked examples", "Printed exit ticket"],
        "source": "template",
    }


def _clean_plan(d, fallback):
    if not isinstance(d, dict):
        return fallback

    def lst(v):
        return [str(x)[:300] for x in v][:6] if isinstance(v, list) else None

    def txt(v):
        return str(v)[:500] if isinstance(v, (str, int, float)) else None
    out = {"objectives": lst(d.get("objectives")), "starter": txt(d.get("starter")), "main": lst(d.get("main")), "check": txt(d.get("check")),
           "differentiation": lst(d.get("differentiation")), "homework": txt(d.get("homework")), "resources": lst(d.get("resources"))}
    if any(v is None or v == [] or v == "" for v in out.values()):
        return fallback
    out["source"] = "ai"
    return out


def lesson_plan(subject, class_name, topic, minutes, level):
    """AI draft when a provider is configured; otherwise (or on any error) the built-in template. Only subject/class/topic are sent."""
    fb = rule_plan(subject, topic, minutes, level)
    try:
        from exams import ai
        if not ai.enabled():
            return fb
        system = ("You are an experienced school teacher. Reply with ONE JSON object with keys: objectives (list of 3 strings), starter (string), main (list of 2-3 strings), "
                  "check (string), differentiation (list of 2 strings), homework (string), resources (list of strings). Include minutes in the text. No other text.")
        text = ai.call_model(system, f"Subject: {subject}\nClass: {class_name}\nTopic: {topic}\nLesson length: {minutes} minutes\nLevel: {level}")
        return _clean_plan(ai.parse_json(text), fb)
    except Exception:
        return fb


# ------------------------------------------------------------------ executive dashboard
def executive(user):
    """One row per campus in the user's scope, with the numbers a head office actually asks for."""
    from attendance.models import AttendanceRecord
    from fees.models import LedgerEntry
    from organization import analytics
    from risk.models import Alert
    rows = analytics.campus_stats(user)
    today = timezone.localdate()
    since = today - timedelta(days=30)
    month = today.replace(day=1)
    for r in rows:
        cid = r["campus"].id
        stu = User.objects.filter(role=User.Role.STUDENT, student_profile__campus_id=cid)
        c = {x["status"]: x["n"] for x in AttendanceRecord.objects.filter(student__in=stu, date__gte=since).values("status").annotate(n=Count("id"))}
        base = c.get("present", 0) + c.get("late", 0) + c.get("absent", 0)
        r["attendance"] = round((c.get("present", 0) + c.get("late", 0)) * 100 / base, 1) if base else None
        led = LedgerEntry.objects.filter(student__in=stu, is_void=False)
        billed = led.filter(month=month, kind="monthly").aggregate(t=Coalesce(Sum("debit"), 0, output_field=DecimalField()))["t"]
        paid = led.filter(kind="payment", entry_date__gte=month).aggregate(t=Coalesce(Sum("credit"), 0, output_field=DecimalField()))["t"]
        r["billed"], r["collected"] = billed, paid
        r["collection"] = round(float(paid) * 100 / float(billed), 1) if billed else None
        r["alerts"] = Alert.objects.filter(student__in=stu).exclude(status="resolved").count()
    return rows
