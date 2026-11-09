"""Weak/strong areas, trends and at-risk detection from computed exam results."""
from assessments.grading import student_summary

from .grading import row_for

WEAK_BELOW = 60      # % — below this a subject is a weak area
STRONG_AT = 80       # % — at/above this (and not below class average) a subject is a strength
BIG_CHANGE = 10      # percentage points vs the previous exam
GAP_BELOW_CLASS = 10 # percentage points under the class average


def student_insights(result, row, prev=None):
    """Everything we know about one student's exam, as plain data (used by the page, the PDF and the AI)."""
    student = row["student"]
    prev_row = row_for(prev, student.id) if prev else None
    prev_by_subject = {}
    if prev_row:
        for c in prev_row["cells"]:
            if c["entered"] and not c["absent"]:
                prev_by_subject[c["paper"].course.subject_id] = c["pct"]
    class_avg = {s["paper"].id: s["avg_pct"] for s in result["stats"]}
    quiz = {x["course"].id: x["avg"] for x in student_summary(student, [p.course for p in result["papers"]])}

    subjects = []
    for c in row["cells"]:
        if not c["entered"]:
            continue
        p = c["paper"]
        pct = None if c["absent"] else c["pct"]
        avg = class_avg.get(p.id)
        before = prev_by_subject.get(p.course.subject_id)
        delta = round(pct - before, 1) if (pct is not None and before is not None) else None
        reasons = []
        if c["absent"]:
            reasons.append("absent")
        else:
            if not c["passed"]:
                reasons.append("failed")
            if pct < WEAK_BELOW:
                reasons.append("below_60")
            if avg is not None and pct < avg - GAP_BELOW_CLASS:
                reasons.append("below_class")
        q = quiz.get(p.course.id)
        if q is not None and q < WEAK_BELOW and not c["absent"]:
            reasons.append("weak_quizzes")
        weak = bool(set(reasons) & {"absent", "failed", "below_60", "below_class"})
        strong = (not weak) and pct is not None and pct >= STRONG_AT and (avg is None or pct >= avg)
        subjects.append({
            "subject": p.subject_name, "marks": c["marks"], "total": p.total_marks, "pct": pct, "grade": c["band"].grade,
            "class_avg": avg, "gap": round(pct - avg, 1) if (pct is not None and avg is not None) else None,
            "prev_pct": before, "delta": delta, "quiz_avg": q, "reasons": reasons,
            "status": "weak" if weak else "strong" if strong else "average",
            "declining": delta is not None and delta <= -BIG_CHANGE, "improving": delta is not None and delta >= BIG_CHANGE,
        })
    subjects.sort(key=lambda s: (s["pct"] is None, s["pct"] if s["pct"] is not None else 0))
    return {
        "student": student, "exam": result["exam"], "overall_pct": row["pct"], "grade": row["band"].grade if row["band"] else None,
        "gpa": row["gpa"], "rank": row["rank"], "n_ranked": result["n_complete"], "result": row["result"],
        "prev_pct": prev_row["pct"] if prev_row and prev_row["complete"] else None,
        "delta": round(row["pct"] - prev_row["pct"], 1) if (prev_row and prev_row["complete"] and row["pct"] is not None) else None,
        "subjects": subjects,
        "weak": [s for s in subjects if s["status"] == "weak"],
        "strong": sorted([s for s in subjects if s["status"] == "strong"], key=lambda s: -s["pct"]),
        "declining": [s for s in subjects if s["declining"]],
        "improving": [s for s in subjects if s["improving"]],
    }


def class_insights(result, prev=None):
    """Class-wide picture: weakest subjects, pass rates, and students who need attention."""
    papers = []
    for s in result["stats"]:
        if s["avg_pct"] is None:
            continue
        flags = []
        if s["avg_pct"] < WEAK_BELOW:
            flags.append("low_average")
        if s["pass_rate"] is not None and s["pass_rate"] < 70:
            flags.append("low_pass_rate")
        papers.append({"subject": s["paper"].subject_name, "avg_pct": s["avg_pct"], "pass_rate": s["pass_rate"],
                       "high": s["high"], "low": s["low"], "absent": s["absent"], "flags": flags,
                       "teacher": s["paper"].course.teacher.display_name if s["paper"].course.teacher else ""})
    papers.sort(key=lambda p: p["avg_pct"])
    at_risk, top = [], []
    for r in result["rows"]:
        if r["pct"] is None:
            continue
        ins = student_insights(result, r, prev)
        why = []
        if r["result"] == "FAIL":
            why.append("failed {} subject(s)".format(sum(1 for c in r["cells"] if c["entered"] and not c["passed"])))
        if r["pct"] < 50:
            why.append("overall below 50%")
        if ins["delta"] is not None and ins["delta"] <= -BIG_CHANGE:
            why.append(f"dropped {abs(ins['delta'])} points")
        if why:
            at_risk.append({"student": r["student"], "pct": r["pct"], "why": why, "weak": [s["subject"] for s in ins["weak"]]})
    for r in sorted((r for r in result["rows"] if r["complete"]), key=lambda r: r["rank"] or 999)[:3]:
        top.append({"student": r["student"], "pct": r["pct"], "rank": r["rank"]})
    done = [r for r in result["rows"] if r["complete"]]
    passed = sum(1 for r in done if r["result"] == "PASS")
    avg = round(sum(r["pct"] for r in done) / len(done), 1) if done else None
    prev_avg = None
    if prev:
        pd = [r for r in prev["rows"] if r["complete"]]
        prev_avg = round(sum(r["pct"] for r in pd) / len(pd), 1) if pd else None
    return {
        "exam": result["exam"], "n_students": len(result["rows"]), "n_complete": len(done), "avg_pct": avg,
        "prev_avg": prev_avg, "pass_pct": round(passed * 100 / len(done), 1) if done else None,
        "subjects": papers, "weak_subjects": [p for p in papers if p["flags"]], "best_subject": papers[-1] if papers else None,
        "at_risk": at_risk, "top": top,
    }
