import csv
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from academics.models import Course, student_class
from accounts.decorators import role_required
from accounts.models import User
from core.models import SchoolSettings

from . import ai, grading, insights
from .forms import AIForm, BandForm, ExamForm, PaperForm
from .models import AISuggestion, Exam, ExamPaper, GradeBand, Mark
from .pdf import report_card_pdf

admin_only = lambda v: login_required(role_required("super_admin")(v))  # noqa: E731


# ------------------------------------------------------------------ access
def _teaches_class(user, exam):
    return user.is_teacher and Course.objects.filter(school_class=exam.school_class, teacher=user).exists()


def _staff(user, exam):
    return user.is_super_admin or _teaches_class(user, exam)


def _can_enter(user, paper):
    return user.is_super_admin or (user.is_teacher and paper.course.teacher_id == user.id)


def _can_view_card(user, exam, student):
    if _staff(user, exam):
        return True
    if not exam.is_published:
        return False
    if user.is_student:
        return user.id == student.id
    return user.is_parent and user.children.filter(pk=student.pk).exists()


def _exam_or_404(pk):
    return get_object_or_404(Exam.objects.select_related("school_class"), pk=pk)


# ------------------------------------------------------------------ lists
@login_required
def exam_list(request):
    u = request.user
    if u.is_super_admin:
        exams = Exam.objects.select_related("school_class")
    elif u.is_teacher:
        exams = Exam.objects.filter(school_class__courses__teacher=u).select_related("school_class").distinct()
    else:
        return redirect("exams:my_results")
    return render(request, "exams/list_manage.html", {"exams": exams, "page": "exams"})


@login_required
def my_results(request, student_pk=None):
    u = request.user
    if student_pk:
        student = get_object_or_404(User, pk=student_pk, role=User.Role.STUDENT)
        if not (u.is_super_admin or (u.is_parent and u.children.filter(pk=student.pk).exists())):
            raise PermissionDenied
    elif u.is_student:
        student = u
    else:
        raise PermissionDenied
    cls = student_class(student)
    exams = Exam.objects.filter(school_class=cls, is_published=True) if cls else Exam.objects.none()
    rows = []
    for e in exams:
        res = grading.compute(e)
        row = grading.row_for(res, student.id)
        rows.append({"exam": e, "row": row})
    return render(request, "exams/list_student.html", {
        "rows": rows, "student": student, "is_parent_view": student.pk != u.pk,
        "page": "child" if student.pk != u.pk else "results", "active_child": student.pk})


# ------------------------------------------------------------------ setup (admin)
@admin_only
def exam_form(request, pk=None):
    obj = get_object_or_404(Exam, pk=pk) if pk else None
    form = ExamForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        e = form.save()
        messages.success(request, "Exam saved." if obj else "Exam created. Now add the subject papers.")
        return redirect("exams:detail", pk=e.pk)
    return render(request, "exams/form.html", {"form": form, "title": "Edit exam" if obj else "New exam", "page": "exams",
                                                "back": "exams:list"})


@admin_only
@require_POST
def exam_delete(request, pk):
    get_object_or_404(Exam, pk=pk).delete()
    messages.success(request, "Exam deleted.")
    return redirect("exams:list")


@login_required
def exam_detail(request, pk):
    exam = _exam_or_404(pk)
    if not _staff(request.user, exam):
        raise PermissionDenied
    prog = grading.entry_progress(exam)
    papers = [{"paper": p, "prog": prog[p.id], "can_enter": _can_enter(request.user, p)}
              for p in exam.papers.select_related("course__subject", "course__teacher")]
    return render(request, "exams/detail.html", {"exam": exam, "papers": papers, "page": "exams",
                                                  "n_students": grading.class_students(exam).count()})


@admin_only
def paper_form(request, exam_pk=None, pk=None):
    obj = get_object_or_404(ExamPaper, pk=pk) if pk else None
    exam = obj.exam if obj else _exam_or_404(exam_pk)
    form = PaperForm(request.POST or None, instance=obj, exam=exam)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.exam = exam
        p.save()
        messages.success(request, "Paper saved.")
        return redirect("exams:detail", pk=exam.pk)
    return render(request, "exams/form.html", {"form": form, "title": f"{'Edit' if obj else 'Add'} subject paper · {exam.name}",
                                                "page": "exams", "back": "exams:detail", "back_arg": exam.pk})


@admin_only
@require_POST
def paper_delete(request, pk):
    p = get_object_or_404(ExamPaper, pk=pk)
    exam = p.exam
    p.delete()
    messages.success(request, "Paper removed.")
    return redirect("exams:detail", pk=exam.pk)


@admin_only
@require_POST
def exam_toggle(request, pk, what):
    exam = _exam_or_404(pk)
    if what == "lock":
        exam.marks_locked = not exam.marks_locked
        messages.success(request, "Marks locked." if exam.marks_locked else "Marks unlocked for editing.")
    elif what == "publish":
        if not exam.is_published and grading.compute(exam)["n_complete"] == 0:
            messages.error(request, "Enter marks first — nothing to publish yet.")
            return redirect("exams:detail", pk=exam.pk)
        exam.is_published = not exam.is_published
        import logging
        logging.getLogger("audit").info("results %s exam=%s by=%s", "published" if exam.is_published else "hidden", exam.pk, request.user.username)
        from core import audit as _audit
        _audit.record(request, "results.publish" if exam.is_published else "results.hide", exam.name, f"exam={exam.pk}")
        messages.success(request, "Results published to students and parents." if exam.is_published else "Results hidden again.")
        if exam.is_published:
            try:
                from academics.models import Enrollment
                from core.notify import notify_family
                for e in Enrollment.objects.filter(school_class=exam.school_class).select_related("student"):
                    notify_family(e.student, f"Results published: {exam.name}", "Open the report card to see marks, grade and position.",
                                  reverse("exams:my_results"), reverse("exams:child_results", args=[e.student_id]), "result")
            except Exception:
                pass
        if exam.is_published:  # weak students automatically receive nuggets for their weak subjects
            try:
                from nuggets.engine import assign_for_exam
                st = assign_for_exam(exam)
                if st["assigned"]:
                    messages.info(request, f"{st['assigned']} nuggets were sent automatically to {st['students']} students for their weak subjects.")
            except Exception:
                pass
    else:
        raise Http404
    exam.save()
    return redirect("exams:detail", pk=exam.pk)


# ------------------------------------------------------------------ marks entry
def _students_for(paper):
    return list(grading.class_students(paper.exam))


def _parse_marks(raw, total):
    raw = (raw or "").strip()
    if raw == "":
        return None, None
    try:
        v = Decimal(raw)
    except InvalidOperation:
        return None, "Not a number"
    if v < 0 or v > total:
        return None, f"Must be between 0 and {total.normalize()}"
    return v, None


@login_required
def marks_entry(request, paper_pk):
    paper = get_object_or_404(ExamPaper.objects.select_related("exam__school_class", "course__subject"), pk=paper_pk)
    if not _can_enter(request.user, paper):
        raise PermissionDenied
    locked = paper.exam.marks_locked
    students = _students_for(paper)
    existing = {m.student_id: m for m in paper.marks.all()}
    rows, errors = [], 0
    for s in students:
        m = existing.get(s.id)
        rows.append({"student": s, "marks": "" if not m or m.marks is None else m.marks.normalize(), "absent": bool(m and m.absent),
                     "remarks": m.remarks if m else "", "error": ""})
    if request.method == "POST":
        if locked:
            messages.error(request, "Marks are locked for this exam. Ask the admin to unlock.")
            return redirect("exams:marks", paper_pk=paper.pk)
        parsed = []
        for r in rows:
            sid = r["student"].id
            raw = request.POST.get(f"m_{sid}", "")
            absent = request.POST.get(f"a_{sid}") == "on"
            rem = request.POST.get(f"r_{sid}", "").strip()[:200]
            r.update(marks=raw.strip(), absent=absent, remarks=rem)
            value, err = (None, None) if absent else _parse_marks(raw, paper.total_marks)
            if err:
                r["error"], errors = err, errors + 1
            parsed.append((sid, value, absent, rem))
        if errors:
            messages.error(request, f"{errors} row(s) need fixing — nothing was saved.")
        else:
            for sid, value, absent, rem in parsed:
                if value is None and not absent and not rem:
                    Mark.objects.filter(paper=paper, student_id=sid).delete()
                else:
                    Mark.objects.update_or_create(paper=paper, student_id=sid, defaults={"marks": value, "absent": absent, "remarks": rem})
            messages.success(request, "Marks saved.")
            return redirect("exams:marks", paper_pk=paper.pk)
    entered = sum(1 for r in rows if r["marks"] != "" or r["absent"])
    return render(request, "exams/marks.html", {"paper": paper, "rows": rows, "locked": locked, "entered": entered,
                                                 "page": "exams"})


@login_required
def marks_import(request, paper_pk):
    paper = get_object_or_404(ExamPaper.objects.select_related("exam__school_class", "course__subject"), pk=paper_pk)
    if not _can_enter(request.user, paper):
        raise PermissionDenied
    students = _students_for(paper)
    if request.GET.get("template"):
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="marks-{paper.pk}.csv"'
        w = csv.writer(resp)
        w.writerow(["username", "name", "marks (number, or ABS for absent)"])
        for s in students:
            w.writerow([s.username, s.display_name, ""])
        return resp
    problems = []
    if request.method == "POST":
        if paper.exam.marks_locked:
            messages.error(request, "Marks are locked for this exam.")
            return redirect("exams:marks", paper_pk=paper.pk)
        f = request.FILES.get("file")
        if not f:
            problems.append("Choose a CSV file.")
        else:
            try:
                text = f.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                text = ""
                problems.append("The file must be a UTF-8 CSV.")
            by_user = {s.username.lower(): s for s in students}
            updates = {}
            for n, rec in enumerate(csv.reader(text.splitlines()), start=1):
                if not rec or not rec[0].strip() or rec[0].strip().lower() == "username":
                    continue
                s = by_user.get(rec[0].strip().lower())
                raw = rec[2].strip() if len(rec) > 2 else (rec[1].strip() if len(rec) == 2 else "")
                if not s:
                    problems.append(f"Line {n}: “{rec[0]}” is not a student of this class.")
                    continue
                if raw.upper() in ("ABS", "A", "ABSENT"):
                    updates[s.id] = (None, True)
                    continue
                v, err = _parse_marks(raw, paper.total_marks)
                if err or v is None:
                    problems.append(f"Line {n} ({rec[0]}): {err or 'marks missing'}.")
                else:
                    updates[s.id] = (v, False)
            if not problems and not updates:
                problems.append("No marks found in the file.")
            if not problems:
                for sid, (v, ab) in updates.items():
                    Mark.objects.update_or_create(paper=paper, student_id=sid, defaults={"marks": v, "absent": ab})
                messages.success(request, f"Imported marks for {len(updates)} student(s).")
                return redirect("exams:marks", paper_pk=paper.pk)
    return render(request, "exams/import.html", {"paper": paper, "problems": problems[:30], "page": "exams"})


# ------------------------------------------------------------------ results
def _result_ctx(exam):
    res = grading.compute(exam)
    return res, grading.compute(grading.previous_exam(exam)) if grading.previous_exam(exam) else None


@login_required
def result_sheet(request, pk):
    exam = _exam_or_404(pk)
    if not _staff(request.user, exam):
        raise PermissionDenied
    res = grading.compute(exam)
    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="results-{exam.pk}.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Rank", "Student", *[p.subject_name for p in res["papers"]], "Total", "Out of", "Percent", "Grade", "GPA", "Result"])
        for r in sorted(res["rows"], key=lambda r: (r["rank"] is None, r["rank"] or 0, r["student"].first_name)):
            w.writerow([r["rank"] or "", r["student"].display_name,
                        *[("ABS" if c["absent"] else c["marks"]) if c["entered"] else "" for c in r["cells"]],
                        r["total"], r["out_of"], r["pct"] if r["pct"] is not None else "", r["band"].grade if r["band"] else "",
                        r["gpa"] if r["gpa"] is not None else "", r["result"]])
        return resp
    rows = sorted(res["rows"], key=lambda r: (r["rank"] is None, r["rank"] or 0, r["student"].first_name))
    return render(request, "exams/sheet.html", {"exam": exam, "res": res, "rows": rows, "page": "exams"})


def _guidance(exam, student, ins, staff):
    """Stored suggestion if staff generated one; otherwise rule-based guidance computed on the fly."""
    saved = AISuggestion.objects.filter(exam=exam, student=student).first()
    if saved:
        return saved.data, saved.data.get("_ur") or ai.rule_student(ins, "ur"), saved
    return ai.rule_student(ins, "en"), ai.rule_student(ins, "ur"), None


def _card_context(request, exam, student):
    res = grading.compute(exam)
    row = grading.row_for(res, student.id)
    if row is None:
        raise Http404
    prev_exam = grading.previous_exam(exam)
    prev = grading.compute(prev_exam) if prev_exam else None
    ins = insights.student_insights(res, row, prev)
    staff = _staff(request.user, exam)
    guidance, guidance_ur, saved = _guidance(exam, student, ins, staff)
    import json
    chart = json.dumps({"type": "bar", "labels": [x["subject"] for x in ins["subjects"]], "values": [x["pct"] for x in ins["subjects"]], "unit": "%", "max": 100,
                        "ref": 33, "refLabel": "Pass", "title": "Subject-wise percentage"}, default=float)
    chart_cmp = json.dumps({"type": "hbar", "labels": ["You", "Class"] if False else [x["subject"] for x in ins["subjects"]], "values": [x["class_avg"] or 0 for x in ins["subjects"]],
                            "unit": "%", "max": 100, "single": True, "title": "Class average"}, default=float)
    return {"chart": chart, "chart_cmp": chart_cmp, "exam": exam, "student": student, "res": res, "row": row, "ins": ins, "guidance": guidance, "guidance_ur": guidance_ur, "saved": saved,
            "subj": {x["subject"]: x for x in ins["subjects"]},
            "staff": staff, "school": SchoolSettings.load().school_name, "prev_exam": prev_exam}


@login_required
def report_card(request, exam_pk, student_pk):
    exam = _exam_or_404(exam_pk)
    student = get_object_or_404(User, pk=student_pk, role=User.Role.STUDENT)
    if not _can_view_card(request.user, exam, student):
        raise PermissionDenied
    ctx = _card_context(request, exam, student)
    ctx.update(page="exams" if ctx["staff"] else ("results" if request.user.is_student else "child"), active_child=student.pk,
               ai_form=AIForm(initial={"language": (ctx["saved"].language if ctx["saved"] else "en")}),
               printing=request.GET.get("print") == "1")
    return render(request, "exams/report_print.html" if ctx["printing"] else "exams/report_card.html", ctx)


@login_required
def report_card_pdf_view(request, exam_pk, student_pk):
    exam = _exam_or_404(exam_pk)
    student = get_object_or_404(User, pk=student_pk, role=User.Role.STUDENT)
    if not _can_view_card(request.user, exam, student):
        raise PermissionDenied
    c = _card_context(request, exam, student)
    data = report_card_pdf(c["school"], c["ins"], c["row"], c["guidance"], c["res"]["stats"], c["res"]["scale"], c["guidance_ur"])
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="report-card-{student.username}.pdf"'
    return resp


# ------------------------------------------------------------------ analysis + AI
@login_required
def analysis(request, pk):
    exam = _exam_or_404(pk)
    if not _staff(request.user, exam):
        raise PermissionDenied
    res = grading.compute(exam)
    prev_exam = grading.previous_exam(exam)
    prev = grading.compute(prev_exam) if prev_exam else None
    cins = insights.class_insights(res, prev)
    saved = AISuggestion.objects.filter(exam=exam, student__isnull=True).first()
    guidance = saved.data if saved else ai.rule_class(cins, "en")
    guidance_ur = (saved.data.get("_ur") if saved else None) or ai.rule_class(cins, "ur")
    import json
    sub = cins["subjects"]
    ch_avg = json.dumps({"type": "bar", "labels": [x["subject"] for x in sub], "values": [x["avg_pct"] for x in sub], "unit": "%", "max": 100, "ref": 33, "refLabel": "Pass"}, default=float)
    ch_pass = json.dumps({"type": "hbar", "labels": [x["subject"] for x in sub], "values": [x["pass_rate"] for x in sub], "unit": "%", "max": 100,
                          "colors": ["#10b981" if x["pass_rate"] >= 70 else ("#f59e0b" if x["pass_rate"] >= 50 else "#f43f5e") for x in sub]}, default=float)
    return render(request, "exams/analysis.html", {
        "ch_avg": ch_avg, "ch_pass": ch_pass, "exam": exam, "res": res, "cins": cins, "guidance": guidance, "guidance_ur": guidance_ur, "saved": saved, "prev_exam": prev_exam,
        "ai_form": AIForm(), "ai_on": ai.enabled(),
        "page": "exams"})


def make_suggestion(exam, student, lang, user):
    """(Re)generate and store suggestions for one student (or the whole class when student is None)."""
    res = grading.compute(exam)
    prev_exam = grading.previous_exam(exam)
    prev = grading.compute(prev_exam) if prev_exam else None
    if student is not None:
        ins = insights.student_insights(res, grading.row_for(res, student.id), prev)
        data, source, model, err = ai.generate_both("student", ai.student_payload(ins), ins)
    else:
        cins = insights.class_insights(res, prev)
        data, source, model, err = ai.generate_both("class", ai.class_payload(cins), cins)
    AISuggestion.objects.filter(exam=exam, student=student).delete()
    AISuggestion.objects.create(exam=exam, student=student, language="both", source=source, model_name=model, data=data, error=err,
                                created_by=user)
    return source, err


@login_required
@require_POST
def ai_generate(request, pk):
    exam = _exam_or_404(pk)
    if not _staff(request.user, exam):
        raise PermissionDenied
    form = AIForm(request.POST)
    lang = form.cleaned_data["language"] if form.is_valid() else "en"
    sid = request.POST.get("student")
    if sid:
        student = get_object_or_404(User, pk=sid, role=User.Role.STUDENT)
        res = grading.compute(exam)
        row = grading.row_for(res, student.id)
        if row is None or row["pct"] is None:
            messages.error(request, "This student has no marks yet.")
            return redirect("exams:report_card", exam_pk=exam.pk, student_pk=student.pk)
        source, err = make_suggestion(exam, student, lang, request.user)
        back = redirect("exams:report_card", exam_pk=exam.pk, student_pk=student.pk)
    else:
        source, err = make_suggestion(exam, None, lang, request.user)
        back = redirect("exams:analysis", pk=exam.pk)
    (messages.warning if err else messages.success)(request, err or ("AI suggestions generated." if source == "ai" else "Suggestions generated."))
    return back


# ------------------------------------------------------------------ student-wise entry
@login_required
def student_list(request, pk):
    """Pick a student to enter all their subject marks on one page."""
    exam = _exam_or_404(pk)
    if not _staff(request.user, exam):
        raise PermissionDenied
    res = grading.compute(exam)
    n = len(res["papers"])
    rows = [{"student": r["student"], "entered": sum(1 for c in r["cells"] if c["entered"]), "n": n, "pct": r["pct"],
             "band": r["band"], "result": r["result"]} for r in res["rows"]]
    return render(request, "exams/students.html", {"exam": exam, "rows": rows, "n_papers": n, "page": "exams"})


@login_required
def student_marks(request, exam_pk, student_pk):
    exam = _exam_or_404(exam_pk)
    if not _staff(request.user, exam):
        raise PermissionDenied
    students = list(grading.class_students(exam))
    student = next((s for s in students if s.pk == student_pk), None)
    if student is None:
        raise Http404
    papers = list(exam.papers.select_related("course__subject", "course__teacher"))
    papers.sort(key=lambda p: p.subject_name)
    existing = {m.paper_id: m for m in Mark.objects.filter(paper__exam=exam, student=student)}
    locked = exam.marks_locked
    rows = []
    for p in papers:
        m = existing.get(p.id)
        rows.append({"paper": p, "editable": (not locked) and _can_enter(request.user, p),
                     "marks": "" if not m or m.marks is None else m.marks.normalize(), "absent": bool(m and m.absent),
                     "remarks": m.remarks if m else "", "error": ""})
    idx = students.index(student)
    nxt = students[idx + 1] if idx + 1 < len(students) else None
    if request.method == "POST":
        if locked:
            messages.error(request, "Marks are locked for this exam. Ask the admin to unlock.")
            return redirect("exams:student_marks", exam_pk=exam.pk, student_pk=student.pk)
        errors, parsed = 0, []
        for r in rows:
            if not r["editable"]:
                continue
            pid = r["paper"].id
            raw = request.POST.get(f"m_{pid}", "")
            absent = request.POST.get(f"a_{pid}") == "on"
            rem = request.POST.get(f"r_{pid}", "").strip()[:200]
            r.update(marks=raw.strip(), absent=absent, remarks=rem)
            value, err = (None, None) if absent else _parse_marks(raw, r["paper"].total_marks)
            if err:
                r["error"], errors = err, errors + 1
            parsed.append((r["paper"], value, absent, rem))
        if errors:
            messages.error(request, f"{errors} subject(s) need fixing — nothing was saved.")
        else:
            for paper, value, absent, rem in parsed:
                if value is None and not absent and not rem:
                    Mark.objects.filter(paper=paper, student=student).delete()
                else:
                    Mark.objects.update_or_create(paper=paper, student=student,
                                                  defaults={"marks": value, "absent": absent, "remarks": rem})
            action = request.POST.get("action", "save")
            lang = request.POST.get("language") if request.POST.get("language") in ("en", "ur") else "en"
            row = grading.row_for(grading.compute(exam), student.id)
            if action == "card" and row and row["pct"] is not None:
                _, err = make_suggestion(exam, student, lang, request.user)
                if err:
                    messages.warning(request, err)
                return redirect(reverse("exams:report_card", args=[exam.pk, student.pk]) + "?print=1")
            messages.success(request, f"Marks saved for {student.display_name}.")
            if action == "next" and nxt:
                return redirect("exams:student_marks", exam_pk=exam.pk, student_pk=nxt.pk)
            return redirect("exams:student_marks", exam_pk=exam.pk, student_pk=student.pk)
    saved = AISuggestion.objects.filter(exam=exam, student=student).first()
    return render(request, "exams/student_marks.html", {
        "exam": exam, "student": student, "students": students, "rows": rows, "locked": locked, "next_student": nxt,
        "any_editable": any(r["editable"] for r in rows), "bands": GradeBand.objects.all(), "lang": saved.language if saved else "en", "page": "exams"})


# ------------------------------------------------------------------ grade scale (admin)
@admin_only
def gradescale(request):
    form = BandForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Grade added.")
        return redirect("exams:gradescale")
    return render(request, "exams/gradescale.html", {"bands": GradeBand.objects.all(), "form": form, "page": "gradescale"})


@admin_only
def gradeband_edit(request, pk):
    obj = get_object_or_404(GradeBand, pk=pk)
    form = BandForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Grade updated.")
        return redirect("exams:gradescale")
    return render(request, "exams/form.html", {"form": form, "title": f"Edit grade {obj.grade}", "page": "gradescale", "back": "exams:gradescale"})


@admin_only
@require_POST
def gradeband_delete(request, pk):
    if GradeBand.objects.count() <= 1:
        messages.error(request, "Keep at least one grade.")
    else:
        get_object_or_404(GradeBand, pk=pk).delete()
        messages.success(request, "Grade removed.")
    return redirect("exams:gradescale")
