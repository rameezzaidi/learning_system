"""Finds what a student is weak at and sends nuggets (and creates them when none exist).

Order of preference for every weak area: (1) a nugget a teacher already made, (2) an earlier auto/AI nugget,
(3) a NEW nugget generated with the configured AI (free Gemini/Groq/Ollama) or, with no AI, built from the
course's own lessons and quiz questions. Generated nuggets are cached per course+topic, so one AI call serves
every student who needs it.
"""
import json
import re

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from academics.models import Enrollment, course_outline
from core.models import SchoolSettings
from core.notify import notify, notify_family
from exams import ai, grading, insights

from . import gamify
from .models import Nugget, StudentNugget

PASS_PCT = 70      # quick check score that counts as "mastered"
WEAK_BELOW = 60    # exam / quiz % under which an area is weak
OPEN_LIMIT = 3     # max unfinished nuggets per student per course
PER_RUN = 2        # new nuggets per weak subject per run
STAGE_DAYS = [3, 7, 21, 60]   # spaced revision: days until the next check after each pass


def _text(html):
    return re.sub(r"\s+", " ", strip_tags(html or "")).strip()


# ------------------------------------------------------------------ topics
def pick_topics(course, student, k):
    """Least-completed modules of the course first (what the student has not studied yet)."""
    mods = [m for m in course_outline(course, student) if m["total"]]
    mods.sort(key=lambda m: (m["pct"], m["module"].position))
    out = []
    for m in mods:
        t = m["module"].title.strip()
        if re.fullmatch(r"module\s*\d+", t, flags=re.I):
            t = f"{course.subject.name} — core ideas"
        if t not in out:
            out.append(t)
    return (out or [f"{course.subject.name} — core ideas"])[:max(k, 1)]


def _material(course, topic):
    lessons = list(course.published_lessons().select_related("module"))
    near = [l for l in lessons if l.module and l.module.title.strip().lower() == topic.lower()]
    return near or lessons


def _course_mcqs(course, n=4):
    from assessments.models import Question
    out = []
    qs = Question.objects.filter(assessment__course=course, kind="mcq").prefetch_related("choices")[:40]
    for q in qs:
        ch = list(q.choices.all())
        ok = [i for i, c in enumerate(ch) if c.is_correct]
        if len(ch) >= 2 and len(ok) == 1:
            out.append({"q": q.text, "options": [c.text for c in ch][:4], "answer": ok[0] if ok[0] < 4 else 0, "why": q.explanation or ""})
        if len(out) >= n:
            break
    return out


# ------------------------------------------------------------------ building a nugget
def _fallback(course, topic, lessons):
    subject = course.subject.name
    texts = [t for t in (_text(l.content) for l in lessons if l.kind == "text") if t]
    body = " ".join(texts)
    sents = [s.strip() for s in re.split(r"(?<=[.!?۔])\s+", body[:2500]) if 25 <= len(s.strip()) <= 220]
    cards = []
    for l in lessons:
        if l.kind == "game" and l.game_type == "flashcards":
            cards += l.game_pairs()
    if sents:
        explanation = body[:700].rsplit(" ", 1)[0] if len(body) > 700 else body
        points = sents[:5]
    else:
        explanation = (f"This nugget helps you revise {topic} in {subject}. Study it in small steps: read the topic once, "
                       f"write it in your own words, solve a few easy questions, then check yourself.")
        points = [f"Read the {topic} notes once without stopping.", "Write the main idea in your own words.",
                  "Solve 5 easy questions, then 5 harder ones.", "Note every mistake and the correct method.",
                  "Ask your teacher about anything still unclear."]
    if not cards:
        cards = [[f"{topic} — point {i + 1}", p] for i, p in enumerate(points[:5])]
    return {"title": f"{topic}: quick revision", "explanation": explanation, "key_points": points,
            "cards": cards[:8], "questions": _course_mcqs(course), "source": Nugget.Source.AUTO}


def _clean_ai(data, fb):
    s = lambda v, n: str(v or "").strip()[:n]
    points = [s(p, 200) for p in (data.get("key_points") or []) if s(p, 200)][:6]
    cards = []
    for c in data.get("cards") or []:
        if isinstance(c, (list, tuple)) and len(c) >= 2 and s(c[0], 120) and s(c[1], 200):
            cards.append([s(c[0], 120), s(c[1], 200)])
    qs = []
    for q in data.get("questions") or []:
        try:
            opts = [s(o, 160) for o in q["options"] if s(o, 160)][:4]
            ans = int(q["answer"])
            if s(q["q"], 300) and 2 <= len(opts) <= 4 and 0 <= ans < len(opts):
                qs.append({"q": s(q["q"], 300), "options": opts, "answer": ans, "why": s(q.get("why"), 300)})
        except (KeyError, TypeError, ValueError):
            continue
    expl = s(data.get("explanation"), 1200)
    if data.get("example"):
        expl += "\n\nExample: " + s(data["example"], 400)
    if not expl or len(points) < 2:
        return None
    return {"title": s(data.get("title"), 200) or fb["title"], "explanation": expl, "key_points": points,
            "cards": cards[:10] or fb["cards"], "questions": qs[:6] or fb["questions"], "source": Nugget.Source.AI}


def _ai_nugget(course, topic, lessons, fb):
    lang = ai.subject_lang(course.subject.name)
    language = "Urdu (written in Urdu script, simple everyday words)" if lang == "urs" else "simple English"
    notes = " ".join(t for t in (_text(l.content) for l in lessons if l.kind == "text") if t)[:2500]
    system = (f"You are an experienced {course.subject.name} teacher. Create ONE short micro-lesson (a 'nugget', 3-5 minutes) on the "
              f"topic for a {course.school_class.name} student who is struggling with it. Use standard curriculum facts and the school's notes "
              f"if given; do not invent facts. Write in {language}. Reply with ONE JSON object only, no markdown: "
              '{"title": "", "explanation": "<=900 chars, step by step", "key_points": ["4-6 short points"], "example": "one worked example", '
              '"cards": [["front","back"] x6], "questions": [{"q": "", "options": ["4 options"], "answer": 0, "why": ""} x4]}. '
              "answer is the 0-based index of the correct option.")
    payload = {"subject": course.subject.name, "class": course.school_class.name, "topic": topic, "school_notes": notes}
    data = ai.parse_json(ai.call_model(system, json.dumps(payload, ensure_ascii=False)))
    return _clean_ai(data, fb)


def generate_nugget(course, topic, created_by=None, force_rules=False):
    """Create (and save) a nugget for course+topic. Uses AI when configured, otherwise the course's own material."""
    lessons = _material(course, topic)
    fb = _fallback(course, topic, lessons)
    built = None
    if not force_rules and ai.enabled():
        try:
            built = _ai_nugget(course, topic, lessons, fb)
        except Exception:
            built = None
    built = built or fb
    mins = max(3, min(8, 2 + len(built["questions"]) + len(built["key_points"]) // 2))
    approved = created_by is not None or SchoolSettings.load().auto_approve_nuggets   # a teacher who asked for it reviews it right away
    nugget = Nugget.objects.create(
        review="approved" if approved else "pending",
        course=course, topic=topic[:120], title=built["title"][:200], explanation=built["explanation"],
        key_points="\n".join(built["key_points"]), cards=built["cards"], questions=built["questions"],
        source=built["source"], minutes=mins, created_by=created_by)
    if not approved and course.teacher_id:
        notify(course.teacher, "A nugget is waiting for your review", f"{nugget.title} · {course.subject.name}", "/nuggets/manage/?review=pending", "review")
    return nugget


# ------------------------------------------------------------------ sending to students
def send(student, nugget, reason="", trigger=StudentNugget.Trigger.SELF, exam=None):
    obj, new = StudentNugget.objects.get_or_create(
        student=student, nugget=nugget, defaults={"reason": reason[:250], "trigger": trigger, "exam": exam})
    if new and nugget.live:
        announce(obj)
    return obj if new else None


def announce(row):
    """Tell the student (and parents) about a nugget that is now visible."""
    n, s = row.nugget, row.student
    notify_family(s, f"New nugget: {n.title}", row.reason or f"{n.course.subject.name} · {n.minutes} min",
                  "/nuggets/", f"/students/{s.pk}/profile/", "nugget")


def approve(nugget, user):
    """Teacher approves an AI/auto nugget: it becomes visible and everyone who was waiting is notified."""
    nugget.review, nugget.reviewed_by, nugget.reviewed_at = "approved", user, timezone.now()
    nugget.save(update_fields=["review", "reviewed_by", "reviewed_at"])
    if nugget.is_published:
        for row in nugget.assignments.select_related("student", "nugget__course__subject"):
            announce(row)


def assign_course(student, course, reason, trigger, exam=None, k=PER_RUN, stats=None):
    """Send up to k nuggets for one weak course. Returns the list of new StudentNugget rows."""
    open_n = StudentNugget.objects.filter(student=student, nugget__course=course).exclude(status="done").count()
    slots = min(k, OPEN_LIMIT - open_n)
    if slots <= 0:
        return []
    have = set(StudentNugget.objects.filter(student=student, nugget__course=course).values_list("nugget_id", flat=True))
    weak_topics = [t.lower() for t in pick_topics(course, student, slots + 1)]
    existing = list(Nugget.objects.filter(course=course, is_published=True, review="approved").exclude(pk__in=have))
    existing.sort(key=lambda n: (n.topic.lower() not in weak_topics, n.source != Nugget.Source.MANUAL, n.id))
    chosen = existing[:slots]
    if len(chosen) < slots:
        known = {n.topic.lower() for n in Nugget.objects.filter(course=course)}
        for t in pick_topics(course, student, slots + 2):
            if len(chosen) >= slots:
                break
            if t.lower() in known:
                continue
            chosen.append(generate_nugget(course, t))
            known.add(t.lower())
            if stats is not None:
                stats["created"] = stats.get("created", 0) + 1
    out = []
    for n in chosen:
        row = send(student, n, reason, trigger, exam)
        if row:
            out.append(row)
    return out


def assign_for_exam(exam):
    """Every student who is weak in a subject of this exam gets nuggets for it. Returns counts."""
    stats = {"students": 0, "assigned": 0, "created": 0}
    res = grading.compute(exam)
    course_by_subject = {p.subject_name: p.course for p in res["papers"]}
    for row in res["rows"]:
        ins = insights.student_insights(res, row, None)
        got = 0
        for s in ins["subjects"]:
            course = course_by_subject.get(s["subject"])
            if course is None or s["status"] != "weak":
                continue
            pct = "absent" if s["pct"] is None else f"{s['pct']}%"
            rows = assign_course(row["student"], course, f"{s['subject']} was {pct} in {exam.name}", StudentNugget.Trigger.EXAM, exam, stats=stats)
            got += len(rows)
        if got:
            stats["students"] += 1
            stats["assigned"] += got
    return stats


def assign_after_attempt(att):
    """A low quiz score sends one nugget for that course."""
    if not att.submitted or att.needs_review:
        return []
    pct = float(att.percent or 0)
    if pct >= WEAK_BELOW:
        return []
    return assign_course(att.student, att.assessment.course, f"Quiz “{att.assessment.title}”: {round(pct)}%", StudentNugget.Trigger.QUIZ, k=1)


def plan_for_student(student):
    """The student's own 'find me nuggets' button: latest published exam + low quiz courses."""
    from academics.models import student_class
    from assessments.grading import student_summary
    from exams.models import Exam

    stats = {"created": 0}
    new = []
    cls = student_class(student)
    if not cls:
        return new
    for e in Exam.objects.filter(school_class=cls, is_published=True).order_by("-start_date", "-id")[:1]:
        res = grading.compute(e)
        row = grading.row_for(res, student.id)
        if row:
            by_subject = {p.subject_name: p.course for p in res["papers"]}
            for s in insights.student_insights(res, row, None)["subjects"]:
                if s["status"] == "weak" and s["subject"] in by_subject:
                    pct = "absent" if s["pct"] is None else f"{s['pct']}%"
                    new += assign_course(student, by_subject[s["subject"]], f"{s['subject']} was {pct} in {e.name}", StudentNugget.Trigger.EXAM, e, stats=stats)
    courses = list(cls.courses.select_related("subject", "school_class"))
    for x in student_summary(student, courses):
        if x["avg"] is not None and x["avg"] < WEAK_BELOW:
            new += assign_course(student, x["course"], f"Quiz average in {x['course'].subject.name} is {round(x['avg'])}%", StudentNugget.Trigger.QUIZ, k=1, stats=stats)
    return new


def assign_to_class(nugget, trigger=StudentNugget.Trigger.MANUAL, reason="Sent by your teacher"):
    n = 0
    for e in Enrollment.objects.filter(school_class=nugget.course.school_class).select_related("student"):
        if send(e.student, nugget, reason, trigger):
            n += 1
    return n


# ------------------------------------------------------------------ quick check
def grade_check(nugget, post):
    """Grade the quick check from POST (q0, q1 ...). Returns (correct, total, per_question_results)."""
    results, correct = [], 0
    for i, q in enumerate(nugget.questions or []):
        raw = post.get(f"q{i}")
        picked = int(raw) if raw is not None and str(raw).isdigit() else None
        ok = picked == q.get("answer")
        correct += ok
        results.append({"ok": ok, "answer": q.get("answer"), "picked": picked, "why": q.get("why", "")})
    return correct, len(results), results


@transaction.atomic
def record(student, nugget, pct, missed=()):
    """Save a quick-check result. Handles mastery, spaced revision, XP, streak and badges.
    Returns (row, extras) where extras = {"xp", "streak", "new_badges", "event"}."""
    row, created = StudentNugget.objects.get_or_create(student=student, nugget=nugget, defaults={"trigger": StudentNugget.Trigger.SELF, "reason": "Opened by you"})
    today = timezone.localdate()
    first_ever = not StudentNugget.objects.filter(student=student, attempts__gt=0).exclude(pk=row.pk).exists() and row.attempts == 0
    was_due = row.due
    row.attempts += 1
    if row.score is None or pct > row.score:
        row.score = round(pct, 1)
    xp, event, reviewed = gamify.XP["attempt"], "tried", False
    if pct >= PASS_PCT:
        if row.status != StudentNugget.Status.DONE:
            row.status, row.completed_at, row.stage = StudentNugget.Status.DONE, timezone.now(), 1
            row.next_review = today + timedelta(days=STAGE_DAYS[0])
            xp, event = gamify.XP["mastered"], "mastered"
        elif was_due:
            row.stage = row.stage + 1
            row.next_review = today + timedelta(days=STAGE_DAYS[min(row.stage - 1, len(STAGE_DAYS) - 1)])
            xp, event, reviewed = gamify.XP["review"], "reviewed", True
        if pct >= 100:
            xp += gamify.XP["perfect"]
    elif was_due:                                   # forgot it: come back tomorrow, start the ladder again
        row.stage, row.next_review, event = 1, today + timedelta(days=1), "forgot"
    row.missed = list(missed)
    row.seen = True
    row.save()
    st = gamify.touch(student, xp)
    mastered = StudentNugget.objects.filter(student=student, status="done").count()
    new = gamify.award_badges(student, st, mastered, perfect=pct >= 100, reviewed=reviewed, tried_first=first_ever)
    return row, {"xp": xp, "total_xp": st.xp, "level": st.level, "streak": st.streak, "new_badges": new, "event": event,
                 "next_review": row.next_review.isoformat() if row.next_review else None}


def missed_of(results):
    return [i for i, r in enumerate(results) if not r["ok"]]
