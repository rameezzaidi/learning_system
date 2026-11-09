"""Campus-level performance numbers, always computed from the campuses the viewer may see."""
from collections import defaultdict

from accounts.models import User
from core import scope

AT_RISK_BELOW = 50.0


def _student_exam_summary(student_ids):
    """{student_id: {"pcts": [...], "latest": pct|None, "fails": n}} from PUBLISHED exams only."""
    from exams import grading
    from exams.models import Exam
    ids = set(student_ids)
    out = defaultdict(lambda: {"pcts": [], "latest": None, "fails": 0})
    exams = Exam.objects.filter(is_published=True).select_related("school_class").order_by("start_date", "id")
    for e in exams:
        res = grading.compute(e)
        for r in res["rows"]:
            sid = r["student"].id
            if sid in ids and r["complete"] and r["pct"] is not None:
                o = out[sid]
                o["pcts"].append(r["pct"])
                o["latest"] = r["pct"]
                if r["result"] == "FAIL":
                    o["fails"] += 1
    return out


def campus_stats(user):
    """One row per visible campus, ranked by average exam percentage."""
    from nuggets.models import StudentNugget
    campuses = list(scope.campuses_for(user))
    students = list(scope.students_for(user).filter(student_profile__campus__in=campuses))
    by_campus = defaultdict(list)
    for s in students:
        by_campus[s.student_profile.campus_id].append(s)
    summ = _student_exam_summary([s.id for s in students])
    nug = defaultdict(lambda: [0, 0])
    for sid, status in StudentNugget.objects.filter(student__in=students, nugget__is_published=True, nugget__review="approved").values_list("student_id", "status"):
        nug[sid][0] += 1
        nug[sid][1] += status == "done"
    teachers = defaultdict(int)
    for cid in User.objects.filter(role=User.Role.TEACHER, is_active=True, campus__in=campuses).values_list("campus_id", flat=True):
        teachers[cid] += 1
    rows = []
    for c in campuses:
        ss = by_campus.get(c.id, [])
        pcts = [p for s in ss for p in summ[s.id]["pcts"]] if ss else []
        graded = [s for s in ss if summ[s.id]["pcts"]]
        risk = [s for s in graded if summ[s.id]["latest"] < AT_RISK_BELOW]
        sent = sum(nug[s.id][0] for s in ss)
        done = sum(nug[s.id][1] for s in ss)
        passed = sum(1 for s in graded if summ[s.id]["fails"] == 0)
        rows.append({
            "campus": c, "region": c.region, "students": len(ss), "active": sum(1 for s in ss if s.is_active),
            "teachers": teachers.get(c.id, 0),
            "avg_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
            "pass_rate": round(passed * 100 / len(graded), 1) if graded else None,
            "graded": len(graded), "at_risk": len(risk), "risk_ids": [s.id for s in risk],
            "mastery": round(done * 100 / sent, 1) if sent else None, "nuggets": sent,
        })
    ranked = sorted((r for r in rows if r["avg_pct"] is not None), key=lambda r: -r["avg_pct"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    for r in rows:
        r.setdefault("rank", None)
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["campus"].name))
    return rows


def totals(rows):
    pcts = [(r["avg_pct"], r["graded"]) for r in rows if r["avg_pct"] is not None]
    w = sum(g for _, g in pcts)
    return {
        "campuses": len(rows), "students": sum(r["students"] for r in rows), "teachers": sum(r["teachers"] for r in rows),
        "avg_pct": round(sum(a * g for a, g in pcts) / w, 1) if w else None,
        "at_risk": sum(r["at_risk"] for r in rows),
    }


def at_risk_students(user, limit=10):
    from organization.models import Campus  # noqa: F401
    students = list(scope.students_for(user))
    summ = _student_exam_summary([s.id for s in students])
    out = [(s, summ[s.id]["latest"]) for s in students if summ[s.id]["pcts"] and summ[s.id]["latest"] < AT_RISK_BELOW]
    out.sort(key=lambda t: t[1])
    return out[:limit]
