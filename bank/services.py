import csv
import io
import random

from django.db import transaction

from accounts.rbac import has_perm
from curriculum.services import courses_for as _courses_for

from .models import BankChoice, BankQuestion

DIFF = {"1": 1, "easy": 1, "2": 2, "medium": 2, "3": 3, "hard": 3}
MAX_ROWS = 500


def courses_for(user):
    if not has_perm(user, "bank.manage"):
        return _courses_for(user).none()
    from academics.models import Course
    qs = Course.objects.select_related("subject", "school_class__campus", "teacher")
    if user.is_teacher:
        return qs.filter(teacher=user)
    return _courses_for(user)


@transaction.atomic
def add_question(course, by, kind, text, topic="", difficulty=2, explanation="", options=(), correct=(), accepted=""):
    """options: list of choice texts; correct: indices that are right. Returns (question, error)."""
    text = (text or "").strip()
    if not text:
        return None, "Write the question."
    if kind == "tf":
        options, correct = ["True", "False"], correct if correct else ()
    if kind in ("mcq", "tf"):
        options = [o.strip() for o in options if o and o.strip()]
        correct = [i for i in correct if 0 <= i < len(options)]
        if len(options) < 2:
            return None, "Give at least two answer options."
        if len(correct) != 1:
            return None, "Mark exactly one correct answer."
    elif kind == "short":
        if not (accepted or "").strip():
            return None, "Give at least one accepted answer."
    else:
        return None, "Unknown question type."
    q = BankQuestion.objects.create(course=course, kind=kind, text=text, topic=(topic or "")[:120], difficulty=difficulty if difficulty in (1, 2, 3) else 2,
                                    explanation=explanation or "", accepted=(accepted or "")[:500], created_by=by)
    for i, o in enumerate(options if kind != "short" else []):
        BankChoice.objects.create(question=q, text=o[:300], is_correct=i in correct, position=i)
    return q, ""


def _safe(cell):
    cell = (cell or "").strip()
    return cell


def import_csv(course, by, fileobj):
    """Columns: topic,difficulty,question,a,b,c,d,correct,explanation. Returns (added, [errors])."""
    raw = fileobj.read(1_000_001)
    if len(raw) > 1_000_000:
        return 0, ["The file is larger than 1 MB."]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return 0, ["Save the CSV as UTF-8."]
    reader = csv.DictReader(io.StringIO(text))
    need = {"question", "a", "b", "correct"}
    if not reader.fieldnames or not need <= {f.strip().lower() for f in reader.fieldnames}:
        return 0, ["The first row must have the columns: topic, difficulty, question, a, b, c, d, correct, explanation."]
    added, errors = 0, []
    for n, row in enumerate(reader, start=2):
        if n > MAX_ROWS + 1:
            errors.append(f"Only the first {MAX_ROWS} rows were read.")
            break
        r = {(k or "").strip().lower(): _safe(v) for k, v in row.items()}
        opts = [r.get(k, "") for k in "abcd"]
        opts_clean = [o for o in opts if o]
        corr = r.get("correct", "").lower()
        idx = ["a", "b", "c", "d"].index(corr) if corr in ("a", "b", "c", "d") else -1
        if idx < 0 or not opts[idx]:
            errors.append(f"Row {n}: 'correct' must be A, B, C or D and match a filled option.")
            continue
        # keep correct pointing at the same text after dropping blanks
        correct_i = opts_clean.index(opts[idx])
        q, err = add_question(course, by, "mcq", r.get("question", ""), r.get("topic", ""), DIFF.get(r.get("difficulty", "").lower(), 2),
                              r.get("explanation", ""), opts_clean, [correct_i])
        if err:
            errors.append(f"Row {n}: {err}")
        else:
            added += 1
    return added, errors


@transaction.atomic
def generate(course, by, title, easy=0, medium=0, hard=0, topic="", duration=0, kind="quiz", rng=None):
    """Build a draft Assessment from random bank questions. Returns (assessment, notes)."""
    from assessments.models import Assessment, Choice, Question
    rng = rng or random.Random()
    notes, picked = [], []
    for level, want in ((1, easy), (2, medium), (3, hard)):
        if want <= 0:
            continue
        pool = list(BankQuestion.objects.filter(course=course, difficulty=level, **({"topic__iexact": topic} if topic else {})))
        if len(pool) < want:
            notes.append(f"Only {len(pool)} {dict([(1, 'easy'), (2, 'medium'), (3, 'hard')])[level]} question(s) available, wanted {want}.")
        picked += rng.sample(pool, min(want, len(pool)))
    if not picked:
        return None, notes or ["Choose how many questions you want."]
    rng.shuffle(picked)
    a = Assessment.objects.create(course=course, title=(title or "Generated paper")[:200], kind=kind if kind in ("quiz", "test", "exam") else "quiz",
                                  duration_minutes=max(0, int(duration or 0)), is_published=False)
    for bq in picked:
        qk = {"mcq": "mcq", "tf": "tf", "short": "short"}[bq.kind]
        q = Question.objects.create(assessment=a, kind=qk, text=bq.text, points=1, explanation=bq.explanation, accepted=bq.accepted)
        chs = list(bq.choices.all())
        if bq.kind == "mcq":
            rng.shuffle(chs)
        for i, c in enumerate(chs):
            Choice.objects.create(question=q, text=c.text, is_correct=c.is_correct, position=i)
    return a, notes
