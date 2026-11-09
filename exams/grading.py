"""Marks → percentage → grade / GPA / rank. Pure computation on top of the stored marks."""
from decimal import Decimal

from accounts.models import User

from .models import DEFAULT_BANDS, Exam, GradeBand, Mark


class _Band:
    def __init__(self, grade, min_percent, points, remark=""):
        self.grade, self.min_percent, self.points, self.remark = grade, float(min_percent), float(points), remark


def bands():
    rows = [_Band(b.grade, b.min_percent, b.points, b.remark) for b in GradeBand.objects.order_by("-min_percent")]
    return rows or [_Band(g, m, p, r) for g, m, p, r in DEFAULT_BANDS]


def band_for(pct, scale=None):
    scale = scale or bands()
    for b in scale:
        if pct >= b.min_percent:
            return b
    return scale[-1]


def grade_letter(pct):
    return "—" if pct is None else band_for(pct).grade


def _pct(marks, total):
    return round(float(marks) * 100 / float(total), 1) if total else 0.0


def class_students(exam):
    return User.objects.filter(role=User.Role.STUDENT, enrollment__school_class=exam.school_class).order_by("first_name", "username")


def compute(exam):
    """Full result set of an exam: per-student rows (with rank) and per-paper statistics."""
    scale = bands()
    papers = list(exam.papers.select_related("course__subject", "course__teacher"))
    students = list(class_students(exam))
    marks = {(m.paper_id, m.student_id): m for m in Mark.objects.filter(paper__exam=exam)}
    rows = []
    for s in students:
        cells, got, out_of, pts, complete, passed_all = [], Decimal("0"), Decimal("0"), [], True, True
        for p in papers:
            m = marks.get((p.id, s.id))
            entered = bool(m and (m.absent or m.marks is not None))
            absent = bool(m and m.absent)
            if not entered:
                complete = False
                cells.append({"paper": p, "entered": False, "absent": False, "marks": None, "pct": None, "band": None, "passed": None, "remarks": ""})
                continue
            value = Decimal("0") if absent else m.marks
            pct = _pct(value, p.total_marks)
            band = band_for(pct, scale)
            passed = (not absent) and value >= p.pass_marks
            if not passed:
                passed_all = False
            got += value
            out_of += p.total_marks
            pts.append(band.points if not absent else 0.0)
            cells.append({"paper": p, "entered": True, "absent": absent, "marks": value, "pct": pct, "band": band,
                          "passed": passed, "remarks": m.remarks})
        pct = _pct(got, out_of) if out_of else None
        band = band_for(pct, scale) if pct is not None else None
        result = "INCOMPLETE" if (not complete or not papers) else ("PASS" if passed_all else "FAIL")
        rows.append({"student": s, "cells": cells, "total": got, "out_of": out_of, "pct": pct, "band": band,
                     "gpa": round(sum(pts) / len(pts), 2) if pts else None, "result": result, "rank": None,
                     "complete": complete and bool(papers)})
    # competition ranking (1,2,2,4) among students whose marks are complete
    ranked = sorted((r for r in rows if r["complete"]), key=lambda r: -r["pct"])
    last_pct, last_rank = None, 0
    for i, r in enumerate(ranked, start=1):
        if r["pct"] != last_pct:
            last_rank, last_pct = i, r["pct"]
        r["rank"] = last_rank
    stats = []
    for i, p in enumerate(papers):
        cs = [r["cells"][i] for r in rows if r["cells"][i]["entered"]]
        present = [c for c in cs if not c["absent"]]
        stats.append({
            "paper": p, "entered": len(cs), "absent": len(cs) - len(present), "students": len(rows),
            "avg_pct": round(sum(c["pct"] for c in present) / len(present), 1) if present else None,
            "high": max((c["marks"] for c in present), default=None), "low": min((c["marks"] for c in present), default=None),
            "pass_rate": round(sum(1 for c in cs if c["passed"]) * 100 / len(cs), 1) if cs else None,
            "dist": {b.grade: sum(1 for c in cs if c["band"] and c["band"].grade == b.grade) for b in scale},
        })
    return {"exam": exam, "papers": papers, "rows": rows, "stats": stats, "scale": scale,
            "n_complete": sum(1 for r in rows if r["complete"])}


def row_for(result, student_id):
    return next((r for r in result["rows"] if r["student"].id == student_id), None)


def previous_exam(exam):
    """The most recent earlier exam of the same class (by date, else by creation order)."""
    qs = Exam.objects.filter(school_class=exam.school_class).exclude(pk=exam.pk)
    if exam.start_date:
        earlier = qs.filter(start_date__lt=exam.start_date).order_by("-start_date", "-id").first()
        if earlier:
            return earlier
    return qs.filter(id__lt=exam.id, start_date__isnull=True).order_by("-id").first() if not exam.start_date else None


def entry_progress(exam):
    """(entered, expected) mark rows per paper, for the exam overview."""
    n = class_students(exam).count()
    out = {}
    for p in exam.papers.all():
        entered = Mark.objects.filter(paper=p).exclude(marks__isnull=True, absent=False).count()
        out[p.id] = {"entered": entered, "expected": n}
    return out
