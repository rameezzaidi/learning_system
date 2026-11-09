import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from academics.models import Course, Enrollment, SchoolClass, Subject
from accounts.models import User

from . import ai, grading, insights
from .models import AISuggestion, Exam, ExamPaper, GradeBand, Mark


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        mk = User.objects.create_user
        cls.admin = mk("adm", password="x", role="super_admin")
        cls.t_math = mk("tm", password="x", role="teacher")
        cls.t_eng = mk("te", password="x", role="teacher")
        cls.t_none = mk("tn", password="x", role="teacher")
        cls.a = mk("a", password="x", role="student", first_name="Aisha")
        cls.b = mk("b", password="x", role="student", first_name="Bilal")
        cls.c = mk("c", password="x", role="student", first_name="Chand")
        cls.out = mk("out", password="x", role="student")
        cls.parent = mk("par", password="x", role="parent")
        cls.parent.children.add(cls.a)
        cls.klass = SchoolClass.objects.create(name="Class 8", section="A")
        other = SchoolClass.objects.create(name="Class 9", section="B")
        for s in (cls.a, cls.b, cls.c):
            Enrollment.objects.create(student=s, school_class=cls.klass)
        Enrollment.objects.create(student=cls.out, school_class=other)
        cls.math = Course.objects.create(school_class=cls.klass, subject=Subject.objects.create(name="Math"), teacher=cls.t_math)
        cls.eng = Course.objects.create(school_class=cls.klass, subject=Subject.objects.create(name="English"), teacher=cls.t_eng)
        cls.exam = Exam.objects.create(name="Mid", school_class=cls.klass)
        cls.p_math = ExamPaper.objects.create(exam=cls.exam, course=cls.math, total_marks=100, pass_marks=33)
        cls.p_eng = ExamPaper.objects.create(exam=cls.exam, course=cls.eng, total_marks=50, pass_marks=20)

    def put(self, paper, student, marks=None, absent=False):
        Mark.objects.create(paper=paper, student=student, marks=marks, absent=absent)

    def fill(self):
        # a: 90/100 + 45/50 = 90% ; b: 40/100 + 25/50 = 43.3% ; c: 90/100 + 45/50 = 90%
        for s, m, e in ((self.a, 90, 45), (self.b, 40, 25), (self.c, 90, 45)):
            self.put(self.p_math, s, m)
            self.put(self.p_eng, s, e)

    def login(self, u):
        self.client.force_login(u)


class GradingTests(Base):
    def test_percent_grade_gpa_rank_ties(self):
        self.fill()
        r = grading.compute(self.exam)
        rows = {x["student"].username: x for x in r["rows"]}
        self.assertEqual(rows["a"]["pct"], 90.0)
        self.assertEqual(rows["a"]["band"].grade, "A+")
        self.assertEqual(rows["a"]["gpa"], 4.0)
        self.assertEqual((rows["a"]["rank"], rows["c"]["rank"], rows["b"]["rank"]), (1, 1, 3))  # 1,1,3 competition ranking
        self.assertEqual(rows["b"]["pct"], 43.3)
        self.assertEqual(rows["b"]["band"].grade, "F")

    def test_pass_fail_per_paper_not_only_overall(self):
        self.put(self.p_math, self.a, 30)    # 30 < pass 33 -> fail even though english is high
        self.put(self.p_eng, self.a, 50)
        r = grading.row_for(grading.compute(self.exam), self.a.id)
        self.assertEqual(r["result"], "FAIL")
        self.assertEqual(r["pct"], 53.3)

    def test_absent_counts_zero_and_fail(self):
        self.put(self.p_math, self.a, absent=True)
        self.put(self.p_eng, self.a, 40)
        r = grading.row_for(grading.compute(self.exam), self.a.id)
        self.assertEqual(r["result"], "FAIL")
        self.assertEqual(r["total"], Decimal("40"))
        self.assertEqual(r["out_of"], Decimal("150"))

    def test_incomplete_has_no_rank(self):
        self.put(self.p_math, self.a, 80)
        r = grading.row_for(grading.compute(self.exam), self.a.id)
        self.assertEqual(r["result"], "INCOMPLETE")
        self.assertIsNone(r["rank"])
        self.assertEqual(r["pct"], 80.0)

    def test_paper_stats(self):
        self.fill()
        self.put(self.p_math, self.out, 10)  # not in this class: must be ignored
        st = grading.compute(self.exam)["stats"][1]  # papers ordered by subject name: English, Math
        self.assertEqual(st["paper"], self.p_math)
        self.assertEqual((st["high"], st["low"], st["entered"]), (Decimal("90"), Decimal("40"), 3))
        self.assertEqual(st["pass_rate"], 100.0)

    def test_custom_grade_scale_drives_grades_everywhere(self):
        self.fill()
        GradeBand.objects.filter(grade="A+").update(min_percent=95)
        r = grading.row_for(grading.compute(self.exam), self.a.id)
        self.assertEqual(r["band"].grade, "A")
        from assessments.grading import letter
        self.assertEqual(letter(92), "A")
        self.assertEqual(letter(None), "—")

    def test_empty_exam_is_safe(self):
        e = Exam.objects.create(name="Empty", school_class=self.klass)
        r = grading.compute(e)
        self.assertEqual(r["n_complete"], 0)
        self.assertTrue(all(x["result"] == "INCOMPLETE" for x in r["rows"]))

    def test_previous_exam(self):
        import datetime
        self.exam.start_date = datetime.date(2026, 11, 1)
        self.exam.save()
        old = Exam.objects.create(name="Old", school_class=self.klass, start_date=datetime.date(2026, 10, 1))
        Exam.objects.create(name="Other class", school_class=SchoolClass.objects.create(name="X"), start_date=datetime.date(2026, 10, 20))
        self.assertEqual(grading.previous_exam(self.exam), old)
        self.assertIsNone(grading.previous_exam(old))


class MarksEntryTests(Base):
    def url(self, paper=None):
        return reverse("exams:marks", args=[(paper or self.p_math).pk])

    def post(self, **kw):
        data = {}
        for s in (self.a, self.b, self.c):
            data[f"m_{s.id}"] = ""
        data.update(kw)
        return self.client.post(self.url(), data)

    def test_teacher_saves_marks_absent_remarks(self):
        self.login(self.t_math)
        r = self.post(**{f"m_{self.a.id}": "85.5", f"a_{self.b.id}": "on", f"r_{self.a.id}": "good"})
        self.assertRedirects(r, self.url())
        m = Mark.objects.get(paper=self.p_math, student=self.a)
        self.assertEqual((m.marks, m.remarks), (Decimal("85.5"), "good"))
        self.assertTrue(Mark.objects.get(paper=self.p_math, student=self.b).absent)
        self.assertFalse(Mark.objects.filter(paper=self.p_math, student=self.c).exists())  # blank = not marked

    def test_invalid_row_saves_nothing(self):
        self.login(self.t_math)
        for bad in ("101", "-1", "abc"):
            r = self.post(**{f"m_{self.a.id}": "50", f"m_{self.b.id}": bad})
            self.assertEqual(r.status_code, 200, bad)
            self.assertContains(r, "nothing was saved")
            self.assertEqual(Mark.objects.count(), 0)

    def test_blank_clears_existing_mark(self):
        self.put(self.p_math, self.a, 70)
        self.login(self.t_math)
        self.post(**{f"m_{self.a.id}": ""})
        self.assertFalse(Mark.objects.filter(student=self.a).exists())

    def test_locked_blocks_writes(self):
        self.exam.marks_locked = True
        self.exam.save()
        self.login(self.t_math)
        self.assertContains(self.client.get(self.url()), "locked")
        self.post(**{f"m_{self.a.id}": "50"})
        self.assertEqual(Mark.objects.count(), 0)

    def test_only_the_subject_teacher_or_admin(self):
        self.login(self.t_eng)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.post(**{f"m_{self.a.id}": "50"}).status_code, 403)
        self.login(self.t_none)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.login(self.a)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.login(self.t_eng)
        self.assertEqual(self.client.get(self.url(self.p_eng)).status_code, 200)
        self.login(self.admin)
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_csv_import_all_or_nothing(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.login(self.t_math)
        url = reverse("exams:marks_import", args=[self.p_math.pk])
        bad = SimpleUploadedFile("m.csv", b"username,name,marks\na,Aisha,80\nghost,Nobody,50\nb,Bilal,150\n")
        r = self.client.post(url, {"file": bad})
        self.assertContains(r, "ghost")
        self.assertContains(r, "Must be between")
        self.assertEqual(Mark.objects.count(), 0)
        good = SimpleUploadedFile("m.csv", "username,name,marks\na,Aisha,80\nb,Bilal,ABS\nc,Chand,60.5\n".encode())
        self.assertRedirects(self.client.post(url, {"file": good}), self.url())
        self.assertEqual(Mark.objects.get(student=self.c).marks, Decimal("60.5"))
        self.assertTrue(Mark.objects.get(student=self.b).absent)

    def test_csv_template_lists_class_only(self):
        self.login(self.t_math)
        body = self.client.get(reverse("exams:marks_import", args=[self.p_math.pk]), {"template": 1}).content.decode()
        self.assertIn("a,Aisha", body)
        self.assertNotIn("out", body.split("\n", 1)[1])


class SetupTests(Base):
    def test_admin_creates_exam_and_papers(self):
        self.login(self.admin)
        r = self.client.post(reverse("exams:create"), {"name": "Final", "school_class": self.klass.pk})
        e = Exam.objects.get(name="Final")
        self.assertRedirects(r, reverse("exams:detail", args=[e.pk]))
        r = self.client.post(reverse("exams:paper_create", args=[e.pk]), {"course": self.math.pk, "total_marks": "80", "pass_marks": "30"})
        self.assertEqual(r.status_code, 302)
        dup = self.client.post(reverse("exams:paper_create", args=[e.pk]), {"course": self.math.pk, "total_marks": "80", "pass_marks": "30"})
        self.assertEqual(dup.status_code, 200)  # same subject twice is not offered
        bad = self.client.post(reverse("exams:paper_create", args=[e.pk]), {"course": self.eng.pk, "total_marks": "50", "pass_marks": "60"})
        self.assertEqual(bad.status_code, 200)

    def test_course_of_another_class_not_offered(self):
        other = Course.objects.create(school_class=SchoolClass.objects.create(name="Z"), subject=Subject.objects.create(name="Art"))
        self.login(self.admin)
        r = self.client.post(reverse("exams:paper_create", args=[self.exam.pk]), {"course": other.pk, "total_marks": "50", "pass_marks": "20"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ExamPaper.objects.filter(course=other).exists())

    def test_teacher_cannot_manage_setup(self):
        self.login(self.t_math)
        self.assertEqual(self.client.post(reverse("exams:create"), {"name": "x", "school_class": self.klass.pk}).status_code, 403)
        self.assertEqual(self.client.post(reverse("exams:toggle", args=[self.exam.pk, "publish"])).status_code, 403)
        self.assertEqual(self.client.post(reverse("exams:paper_delete", args=[self.p_math.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("exams:gradescale")).status_code, 403)

    def test_publish_needs_marks_and_toggles(self):
        self.login(self.admin)
        self.client.post(reverse("exams:toggle", args=[self.exam.pk, "publish"]))
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.is_published)
        self.fill()
        self.client.post(reverse("exams:toggle", args=[self.exam.pk, "publish"]))
        self.exam.refresh_from_db()
        self.assertTrue(self.exam.is_published)
        self.client.post(reverse("exams:toggle", args=[self.exam.pk, "lock"]))
        self.exam.refresh_from_db()
        self.assertTrue(self.exam.marks_locked)
        self.assertEqual(self.client.post(reverse("exams:toggle", args=[self.exam.pk, "bogus"])).status_code, 404)

    def test_exam_lists_by_role(self):
        self.login(self.t_math)
        self.assertContains(self.client.get(reverse("exams:list")), "Mid")
        self.login(self.t_none)
        self.assertNotContains(self.client.get(reverse("exams:list")), "Mid")
        self.login(self.a)
        self.assertRedirects(self.client.get(reverse("exams:list")), reverse("exams:my_results"))

    def test_gradescale_admin_crud(self):
        self.login(self.admin)
        self.client.post(reverse("exams:gradescale"), {"grade": "A*", "min_percent": "95", "points": "4.0", "remark": "Top"})
        b = GradeBand.objects.get(grade="A*")
        self.client.post(reverse("exams:gradeband_edit", args=[b.pk]), {"grade": "A*", "min_percent": "96", "points": "4.0", "remark": "Top"})
        b.refresh_from_db()
        self.assertEqual(b.min_percent, 96)
        self.client.post(reverse("exams:gradeband_delete", args=[b.pk]))
        self.assertFalse(GradeBand.objects.filter(pk=b.pk).exists())


class VisibilityTests(Base):
    def setUp(self):
        self.fill()

    def card(self, student=None):
        return reverse("exams:report_card", args=[self.exam.pk, (student or self.a).pk])

    def test_unpublished_hidden_from_students_and_parents_but_not_staff(self):
        for u in (self.a, self.parent):
            self.login(u)
            self.assertEqual(self.client.get(self.card()).status_code, 403, u.username)
        for u in (self.admin, self.t_math, self.t_eng):
            self.login(u)
            self.assertEqual(self.client.get(self.card()).status_code, 200, u.username)
        self.login(self.t_none)
        self.assertEqual(self.client.get(self.card()).status_code, 403)

    def test_published_visibility_rules(self):
        self.exam.is_published = True
        self.exam.save()
        self.login(self.a)
        self.assertEqual(self.client.get(self.card()).status_code, 200)
        self.assertEqual(self.client.get(self.card(self.b)).status_code, 403)       # another student's card
        self.login(self.parent)
        self.assertEqual(self.client.get(self.card()).status_code, 200)
        self.assertEqual(self.client.get(self.card(self.b)).status_code, 403)       # not their child
        self.login(self.out)
        self.assertEqual(self.client.get(self.card()).status_code, 403)

    def test_student_and_parent_results_lists(self):
        self.exam.is_published = True
        self.exam.save()
        self.login(self.a)
        r = self.client.get(reverse("exams:my_results"))
        self.assertContains(r, "Mid")
        self.assertContains(r, "90.0%")
        self.login(self.parent)
        self.assertContains(self.client.get(reverse("exams:child_results", args=[self.a.pk])), "Mid")
        self.assertEqual(self.client.get(reverse("exams:child_results", args=[self.b.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("exams:my_results")).status_code, 403)

    def test_teacher_note_hidden_from_students(self):
        self.exam.is_published = True
        self.exam.save()
        self.login(self.a)
        body = self.client.get(self.card()).content.decode()
        self.assertNotIn("Note for teachers", body)
        self.login(self.admin)
        self.assertIn("Note for teachers", self.client.get(self.card(self.b)).content.decode())

    def test_pdf_and_print(self):
        self.login(self.admin)
        r = self.client.get(reverse("exams:report_card_pdf", args=[self.exam.pk, self.b.pk]))
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertContains(self.client.get(self.card(), {"print": 1}), "window.print")

    def test_sheet_and_csv(self):
        self.login(self.t_math)
        r = self.client.get(reverse("exams:sheet", args=[self.exam.pk]))
        self.assertContains(r, "Aisha")
        csv_text = self.client.get(reverse("exams:sheet", args=[self.exam.pk]), {"format": "csv"}).content.decode("utf-8-sig")
        lines = csv_text.strip().splitlines()
        self.assertTrue(lines[0].startswith("Rank,Student,English,Math"))
        self.assertEqual(len(lines), 4)
        self.login(self.a)
        self.assertEqual(self.client.get(reverse("exams:sheet", args=[self.exam.pk])).status_code, 403)


class InsightTests(Base):
    def make_prev(self):
        import datetime
        self.exam.start_date = datetime.date(2026, 11, 1)
        self.exam.save()
        old = Exam.objects.create(name="Old", school_class=self.klass, start_date=datetime.date(2026, 10, 1))
        po = ExamPaper.objects.create(exam=old, course=self.math, total_marks=100, pass_marks=33)
        pe = ExamPaper.objects.create(exam=old, course=self.eng, total_marks=100, pass_marks=33)
        for s in (self.a, self.b, self.c):
            self.put(po, s, 80)
            self.put(pe, s, 80)
        return old

    def test_weak_strong_declining_flags(self):
        self.fill()
        self.make_prev()
        res = grading.compute(self.exam)
        prev = grading.compute(grading.previous_exam(self.exam))
        ins = insights.student_insights(res, grading.row_for(res, self.b.id), prev)
        weak = {s["subject"]: s for s in ins["weak"]}
        self.assertEqual(set(weak), {"Math", "English"})   # 40% and 50% both under 60
        self.assertTrue(weak["Math"]["declining"])          # 80 -> 40
        self.assertEqual(weak["Math"]["delta"], -40.0)
        good = insights.student_insights(res, grading.row_for(res, self.a.id), prev)
        self.assertEqual({s["subject"] for s in good["strong"]}, {"Math", "English"})
        self.assertEqual(good["weak"], [])

    def test_below_class_average_and_absent_are_weak(self):
        for s in (self.a, self.b, self.c):
            self.put(self.p_math, s, 95)
        self.put(self.p_math, self.out, 0)
        Mark.objects.filter(paper=self.p_math, student=self.c).update(marks=Decimal("70"))   # passes, >60, but 20+ under class avg
        self.put(self.p_eng, self.a, absent=True)
        res = grading.compute(self.exam)
        c = insights.student_insights(res, grading.row_for(res, self.c.id))
        self.assertIn("below_class", c["subjects"][-1]["reasons"] if c["subjects"][-1]["subject"] == "Math" else c["subjects"][0]["reasons"])
        a = insights.student_insights(res, grading.row_for(res, self.a.id))
        self.assertIn("absent", next(s for s in a["subjects"] if s["subject"] == "English")["reasons"])

    def test_class_insights(self):
        self.fill()
        res = grading.compute(self.exam)
        ci = insights.class_insights(res)
        self.assertEqual(ci["n_complete"], 3)
        self.assertEqual(ci["pass_pct"], 100.0)  # b: 40>=33 and 25>=20, so everyone passes
        self.assertEqual(ci["avg_pct"], 74.4)
        self.assertEqual([s["subject"] for s in ci["subjects"]][0], "Math")  # weakest first (avg 63.3 vs 73.3)

    def test_quiz_scores_feed_weak_flag(self):
        from assessments.models import Assessment, Attempt
        self.fill()
        a = Assessment.objects.create(course=self.math, title="Q", is_published=True)
        from django.utils import timezone
        Attempt.objects.create(assessment=a, student=self.a, submitted_at=timezone.now(), score=1, total=10)
        res = grading.compute(self.exam)
        ins = insights.student_insights(res, grading.row_for(res, self.a.id))
        math = next(s for s in ins["subjects"] if s["subject"] == "Math")
        self.assertEqual(math["quiz_avg"], 10.0)
        self.assertIn("weak_quizzes", math["reasons"])


class AITests(Base):
    def setUp(self):
        for s, m, e in ((self.a, 90, 45), (self.b, 25, 15), (self.c, 70, 30)):
            self.put(self.p_math, s, m)
            self.put(self.p_eng, s, e)
        self.login(self.t_math)

    def gen(self, student=None, lang="en"):
        data = {"language": lang}
        if student:
            data["student"] = student.pk
        return self.client.post(reverse("exams:ai", args=[self.exam.pk]), data)

    @override_settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="")
    def test_no_key_uses_rules_and_saves(self):
        r = self.gen(self.b)
        self.assertRedirects(r, reverse("exams:report_card", args=[self.exam.pk, self.b.pk]))
        s = AISuggestion.objects.get(student=self.b)
        self.assertEqual(s.source, "rules")
        self.assertTrue(s.data["weak_areas"])
        self.assertIn("Math", s.data["summary"] + json.dumps(s.data["weak_areas"]))
        self.assertContains(self.client.get(reverse("exams:report_card", args=[self.exam.pk, self.b.pk])), "Auto guidance")

    @override_settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="")
    def test_urdu_script_rules(self):
        self.gen(self.b)
        s = AISuggestion.objects.get(student=self.b)
        self.assertEqual(s.language, "both")
        self.assertIn("توجہ درکار ہے", s.data["_ur"]["summary"])      # the Urdu copy (Urdu script) is stored next to the English one
        self.assertNotIn("توجہ", s.data["summary"])

    @override_settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="k", AI_MODEL="m")
    def test_ai_success_and_payload_is_anonymous(self):
        reply = json.dumps({"summary": "AI says hi", "strengths": ["x"], "weak_areas": [{"subject": "Math", "issue": "i", "advice": "a"}],
                            "action_plan": ["w1"], "teacher_note": "t", "parent_note": "p", "motivation": "go"})
        with mock.patch("exams.ai.call_model", return_value="```json\n" + reply + "\n```") as m:
            self.gen(self.b)
        system, user_text = m.call_args[0]
        for secret in ("Bilal", "username", '"b"', "Aisha", "Chand"):
            self.assertNotIn(secret, user_text)
        self.assertIn("percent", user_text)
        s = AISuggestion.objects.get(student=self.b)
        self.assertEqual((s.source, s.model_name, s.data["summary"]), ("ai", "m", "AI says hi"))

    @override_settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="k")
    def test_ai_failure_falls_back_with_message(self):
        with mock.patch("exams.ai.call_model", side_effect=OSError("down")):
            r = self.gen(self.b)
        s = AISuggestion.objects.get(student=self.b)
        self.assertEqual(s.source, "rules")
        self.assertIn("AI unavailable", s.error)
        self.assertTrue(s.data["summary"])

    @override_settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="k")
    def test_bad_json_and_partial_json_are_repaired(self):
        with mock.patch("exams.ai.call_model", return_value="not json at all"):
            self.gen(self.b)
        self.assertEqual(AISuggestion.objects.get(student=self.b).source, "rules")
        partial = json.dumps({"summary": "S", "weak_areas": "oops", "action_plan": [1, None, "step"]})
        with mock.patch("exams.ai.call_model", return_value=partial):
            self.gen(self.b)
        d = AISuggestion.objects.get(student=self.b)
        self.assertEqual(d.source, "ai")
        self.assertEqual(d.data["summary"], "S")
        self.assertTrue(d.data["weak_areas"])        # filled from the rule-based text
        self.assertEqual(d.data["action_plan"], ["1", "step"])

    @override_settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="")
    def test_one_saved_suggestion_per_student_and_class(self):
        self.gen(self.b)
        self.gen(self.b)
        self.gen()
        self.gen()
        self.assertEqual(AISuggestion.objects.filter(student=self.b).count(), 1)
        self.assertEqual(AISuggestion.objects.filter(student__isnull=True).count(), 1)
        self.assertContains(self.client.get(reverse("exams:analysis", args=[self.exam.pk])), "Overall suggestions")

    def test_who_may_generate(self):
        self.login(self.t_none)
        self.assertEqual(self.gen(self.b).status_code, 403)
        self.login(self.b)
        self.assertEqual(self.gen(self.b).status_code, 403)
        self.login(self.parent)
        self.assertEqual(self.gen(self.a).status_code, 403)
        self.assertEqual(AISuggestion.objects.count(), 0)

    @override_settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="")
    def test_students_see_saved_guidance_once_published(self):
        self.gen(self.b)
        self.exam.is_published = True
        self.exam.save()
        self.login(self.b)
        r = self.client.get(reverse("exams:report_card", args=[self.exam.pk, self.b.pk]))
        self.assertContains(r, "Weak areas")
        self.assertNotContains(r, "Generate with AI")
        self.assertNotContains(r, "Regenerate")


class ProviderTests(TestCase):
    @override_settings(AI_PROVIDER="auto", GEMINI_API_KEY="", GROQ_API_KEY="", ANTHROPIC_API_KEY="")
    def test_auto_without_keys_is_rules_only(self):
        self.assertEqual(ai.provider(), "")
        self.assertFalse(ai.enabled())

    @override_settings(AI_PROVIDER="auto", GEMINI_API_KEY="g", GROQ_API_KEY="q", ANTHROPIC_API_KEY="a", AI_MODEL="")
    def test_auto_prefers_free_providers(self):
        self.assertEqual(ai.provider(), "gemini")
        self.assertEqual(ai.model_name(), "gemini-2.0-flash")

    @override_settings(AI_PROVIDER="ollama", GEMINI_API_KEY="", AI_MODEL="")
    def test_ollama_needs_no_key(self):
        self.assertEqual(ai.provider(), "ollama")

    @override_settings(AI_PROVIDER="rules", GEMINI_API_KEY="g")
    def test_rules_forces_off(self):
        self.assertFalse(ai.enabled())

    @override_settings(AI_PROVIDER="gemini", GEMINI_API_KEY="g", AI_MODEL="")
    def test_gemini_request_and_parse(self):
        reply = {"candidates": [{"content": {"parts": [{"text": "{\"a\":1}"}]}}]}
        with mock.patch("exams.ai._post", return_value=reply) as m:
            self.assertEqual(ai.call_model("sys", "usr"), "{\"a\":1}")
        url, payload, headers = m.call_args[0]
        self.assertIn("gemini-2.0-flash:generateContent", url)
        self.assertEqual(headers["x-goog-api-key"], "g")
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "usr")

    @override_settings(AI_PROVIDER="groq", GROQ_API_KEY="q", AI_MODEL="")
    def test_groq_request_and_parse(self):
        with mock.patch("exams.ai._post", return_value={"choices": [{"message": {"content": "{}"}}]}) as m:
            self.assertEqual(ai.call_model("sys", "usr"), "{}")
        url, payload, headers = m.call_args[0]
        self.assertIn("api.groq.com", url)
        self.assertEqual(headers["authorization"], "Bearer q")
        self.assertEqual(payload["messages"][0]["role"], "system")

    @override_settings(AI_PROVIDER="ollama", OLLAMA_URL="http://box:11434/", AI_MODEL="")
    def test_ollama_request_and_parse(self):
        with mock.patch("exams.ai._post", return_value={"message": {"content": "{}"}}) as m:
            self.assertEqual(ai.call_model("sys", "usr"), "{}")
        self.assertEqual(m.call_args[0][0], "http://box:11434/api/chat")


class StudentWiseTests(Base):
    def url(self, student=None):
        return reverse("exams:student_marks", args=[self.exam.pk, (student or self.a).pk])

    def data(self, math="80", eng="40", **kw):
        d = {f"m_{self.p_math.id}": math, f"m_{self.p_eng.id}": eng, "action": "save"}
        d.update(kw)
        return d

    def test_admin_enters_all_subjects_at_once(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        r = self.client.post(self.url(), self.data(**{f"r_{self.p_math.id}": "neat work"}))
        self.assertRedirects(r, self.url())
        self.assertEqual(Mark.objects.get(paper=self.p_math, student=self.a).marks, Decimal("80"))
        self.assertEqual(Mark.objects.get(paper=self.p_eng, student=self.a).marks, Decimal("40"))
        self.assertEqual(Mark.objects.get(paper=self.p_math, student=self.a).remarks, "neat work")

    def test_one_bad_subject_saves_nothing(self):
        self.login(self.admin)
        r = self.client.post(self.url(), self.data(eng="999"))
        self.assertContains(r, "nothing was saved")
        self.assertEqual(Mark.objects.count(), 0)

    def test_teacher_only_edits_own_subject(self):
        self.login(self.t_math)
        self.client.post(self.url(), self.data(math="70", eng="50"))
        self.assertEqual(Mark.objects.get(student=self.a).marks, Decimal("70"))   # math only
        self.assertEqual(Mark.objects.filter(paper=self.p_eng).count(), 0)         # english ignored
        self.login(self.t_none)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.login(self.a)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_locked_blocks_and_outsider_404(self):
        self.exam.marks_locked = True
        self.exam.save()
        self.login(self.admin)
        self.client.post(self.url(), self.data())
        self.assertEqual(Mark.objects.count(), 0)
        self.exam.marks_locked = False
        self.exam.save()
        self.assertEqual(self.client.get(self.url(self.out)).status_code, 404)

    def test_save_and_next_goes_to_next_student(self):
        self.login(self.admin)
        r = self.client.post(self.url(), self.data(action="next"))
        students = list(grading.class_students(self.exam))
        self.assertRedirects(r, self.url(students[students.index(self.a) + 1]))

    @override_settings(AI_PROVIDER="rules")
    def test_save_and_print_makes_suggestions_and_opens_print(self):
        self.login(self.admin)
        r = self.client.post(self.url(), self.data(math="20", eng="10", action="card", language="ur"))
        self.assertRedirects(r, reverse("exams:report_card", args=[self.exam.pk, self.a.pk]) + "?print=1", fetch_redirect_response=False)
        s = AISuggestion.objects.get(student=self.a)
        self.assertTrue(s.data["weak_areas"])
        self.assertTrue(s.data["_ur"]["weak_areas"])
        page = self.client.get(reverse("exams:report_card", args=[self.exam.pk, self.a.pk]), {"print": 1})
        body = page.content.decode()
        self.assertIn("Overall: 30 / 150 = 20.0%", body)
        self.assertIn("Weak areas", body)
        self.assertIn("Remarks", body)
        self.assertNotIn("Note for teachers", body.replace('class="no-print"', ""))  # staff-only note is not printed

    def test_student_list_page(self):
        self.login(self.t_math)
        self.assertContains(self.client.get(reverse("exams:students", args=[self.exam.pk])), "Aisha")
        self.login(self.a)
        self.assertEqual(self.client.get(reverse("exams:students", args=[self.exam.pk])).status_code, 403)


class CardLayoutTests(Base):
    def test_weak_row_class_does_not_collide_with_weak_area_grid(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parent.parent / "static/css/app.css").read_text()
        self.assertNotIn("\n.weak {", css)        # must be scoped to div.weak or table rows turn into grids


class StudyPlanTests(Base):
    def setUp(self):
        self.put(self.p_math, self.b, 20)     # weak, fails
        self.put(self.p_eng, self.b, 22)      # weak
        self.put(self.p_math, self.a, 95)
        self.put(self.p_eng, self.a, 48)
        self.login(self.admin)

    def ins(self, student):
        res = grading.compute(self.exam)
        return insights.student_insights(res, grading.row_for(res, student.id))

    def test_rules_build_weekly_plan_and_timetable_in_both_languages(self):
        ins = self.ins(self.b)
        for lang, sunday in (("en", "Weekly revision + rest · ہفتے بھر کی دہرائی + آرام"), ("ur", "Weekly revision + rest · ہفتے بھر کی دہرائی + آرام")):
            g = ai.rule_student(ins, lang)
            self.assertEqual({p["subject"] for p in g["subject_plans"]}, {"Math", "English"})
            p = next(x for x in g["subject_plans"] if x["subject"] == "Math")
            self.assertEqual(len(p["weeks"]), 4)
            self.assertEqual(p["target"], 50)                 # 20% + 15 is under 50, so the floor target is 50
            self.assertEqual(p["daily_minutes"], 45)          # failing subject gets more time
            self.assertEqual(len(g["timetable"]), 7)
            self.assertEqual(g["timetable"][-1]["subject"], sunday)
            self.assertEqual({t["subject"] for t in g["timetable"][:6]}, {"Math", "English"})

    def test_general_habits_do_not_repeat_the_weekly_plan(self):
        g = ai.rule_student(self.ins(self.b), "en")
        self.assertEqual(len(g["action_plan"]), 1)
        self.assertNotIn("Week 1", g["action_plan"][0])

    def test_no_weak_subject_means_no_plan(self):
        for s in (self.a, self.b, self.c):
            Mark.objects.filter(student=s).delete()
            self.put(self.p_math, s, 90)
            self.put(self.p_eng, s, 45)
        g = ai.rule_student(self.ins(self.a), "en")
        self.assertEqual((g["subject_plans"], g["timetable"]), ([], []))

    @override_settings(AI_PROVIDER="gemini", GEMINI_API_KEY="g")
    def test_ai_called_once_per_language_and_plan_is_merged(self):
        calls = []

        def fake(system, user_text):
            calls.append(system)
            return json.dumps({"summary": "S", "subject_plans": [
                {"subject": "Math", "weeks": [{"title": "W1", "tasks": ["do x", "do y"]}], "checkpoint": "ck"},
                {"subject": "Ghost", "weeks": [], "checkpoint": "no such subject"}]})
        with mock.patch("exams.ai.call_model", side_effect=fake):
            self.client.post(reverse("exams:ai", args=[self.exam.pk]), {"student": self.b.pk})
        self.assertEqual(len(calls), 2)
        self.assertIn("Urdu script", calls[1])
        d = AISuggestion.objects.get(student=self.b).data
        plans = {p["subject"]: p for p in d["subject_plans"]}
        self.assertEqual(set(plans), {"Math", "English"})        # unknown subject dropped, missing one filled from rules
        self.assertEqual(plans["Math"]["weeks"][0]["tasks"], ["do x", "do y"])
        self.assertEqual(plans["Math"]["daily_minutes"], 45)     # numbers always come from the rules
        self.assertEqual(len(plans["English"]["weeks"]), 4)
        self.assertEqual(d["_ur"]["summary"], "S")

    @override_settings(AI_PROVIDER="gemini", GEMINI_API_KEY="g")
    def test_one_language_failing_falls_back_for_that_language_only(self):
        n = {"i": 0}

        def fake(system, user_text):
            n["i"] += 1
            if n["i"] == 2:
                raise OSError("down")
            return json.dumps({"summary": "AI english"})
        with mock.patch("exams.ai.call_model", side_effect=fake):
            self.client.post(reverse("exams:ai", args=[self.exam.pk]), {"student": self.b.pk})
        s = AISuggestion.objects.get(student=self.b)
        self.assertEqual(s.source, "ai")
        self.assertEqual(s.data["summary"], "AI english")
        self.assertIn("توجہ درکار ہے", s.data["_ur"]["summary"])
        self.assertIn("AI unavailable", s.error)

    def test_card_shows_both_languages_and_plan_even_before_generating(self):
        r = self.client.get(reverse("exams:report_card", args=[self.exam.pk, self.b.pk]))
        body = r.content.decode()
        for needle in ("Week 1", "Weekly revision + rest", "Mon · پیر", "Goal 50%", "45 min daily", "کمزور مضامین", ">اردو<", "والدین کے لیے نوٹ"):
            self.assertIn(needle, body)
        for roman in ("Roman Urdu", "Tawajjo", "Kamzor", "Walidain", "Mazboot", "Hafta 1", "Peer"):
            self.assertNotIn(roman, body)

    def test_pdf_contains_both_languages(self):
        r = self.client.get(reverse("exams:report_card_pdf", args=[self.exam.pk, self.b.pk]))
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertGreater(r.content.count(b"/Type /Page\n") + r.content.count(b"/Type /Page "), 1)   # English + Urdu start on separate pages

    def test_student_sees_plan_but_not_teacher_note(self):
        self.exam.is_published = True
        self.exam.save()
        self.login(self.b)
        body = self.client.get(reverse("exams:report_card", args=[self.exam.pk, self.b.pk])).content.decode()
        self.assertIn("Study plan for the student", body)
        self.assertNotIn("Note for teachers", body)
        self.assertNotIn("Teacher ke liye note", body)

    def test_class_analysis_has_both_languages(self):
        for s in (self.a, self.b, self.c):
            Mark.objects.get_or_create(paper=self.p_math, student=s, defaults={"marks": 50})
            Mark.objects.get_or_create(paper=self.p_eng, student=s, defaults={"marks": 20})
        body = self.client.get(reverse("exams:analysis", args=[self.exam.pk])).content.decode()
        self.assertIn("اہم نتائج", body)
        self.assertIn("Key findings", body)
        self.assertNotIn("Aham nataij", body)



class SubjectLanguageTests(Base):
    """Urdu / Islamiat subjects get Urdu-script guidance; every other subject stays in English."""

    def setUp(self):
        self.urdu = Course.objects.create(school_class=self.klass, subject=Subject.objects.create(name="Urdu"), teacher=self.t_eng)
        self.isl = Course.objects.create(school_class=self.klass, subject=Subject.objects.create(name="Islamiat"), teacher=self.t_eng)
        self.p_urdu = ExamPaper.objects.create(exam=self.exam, course=self.urdu, total_marks=100, pass_marks=33)
        self.p_isl = ExamPaper.objects.create(exam=self.exam, course=self.isl, total_marks=100, pass_marks=33)
        for paper, m in ((self.p_math, 20), (self.p_eng, 10), (self.p_urdu, 25), (self.p_isl, 30)):
            self.put(paper, self.b, m)
        for paper in (self.p_math, self.p_eng, self.p_urdu, self.p_isl):
            self.put(paper, self.a, paper.total_marks * Decimal("0.9"))
        self.login(self.admin)

    def guidance(self):
        res = grading.compute(self.exam)
        return ai.rule_student(insights.student_insights(res, grading.row_for(res, self.b.id)), "en")

    def test_subject_kind(self):
        from core.subjects import subject_kind
        self.assertEqual([subject_kind(x) for x in ("Mathematics", "Maths", "Urdu", "Islamiat", "Islamic Studies", "English", "English Grammar", "Science")],
                         ["math", "math", "urdu", "urdu", "urdu", "english", "english", "general"])

    def test_urdu_and_islamiat_in_urdu_script_rest_in_english(self):
        g = self.guidance()
        by = {w["subject"]: w for w in g["weak_areas"]}
        for name in ("Urdu", "Islamiat"):
            self.assertEqual(by[name]["lang"], "urs")
            self.assertRegex(by[name]["advice"], r"[\u0600-\u06FF]")        # Urdu script
            self.assertNotRegex(by[name]["advice"], r"[A-Za-z]")
        for name in ("Math", "English"):
            self.assertEqual(by[name]["lang"], "en")
            self.assertNotRegex(by[name]["advice"], r"[\u0600-\u06FF]")
        plans = {p["subject"]: p for p in g["subject_plans"]}
        self.assertEqual(plans["Islamiat"]["lang"], "urs")
        self.assertRegex(plans["Islamiat"]["weeks"][0]["title"], r"[\u0600-\u06FF]")
        self.assertEqual(plans["Math"]["weeks"][0]["title"], "Week 1 — Basics")

    def test_card_renders_urdu_blocks_rtl(self):
        body = self.client.get(reverse("exams:report_card", args=[self.exam.pk, self.b.pk])).content.decode()
        self.assertIn('dir="rtl" lang="ur"', body)
        self.assertIn("روزانہ", body)
        self.assertEqual(body.count('class="plan urs"'), 2)

    @override_settings(AI_PROVIDER="gemini", GEMINI_API_KEY="g")
    def test_ai_gets_a_third_urdu_script_call_only_for_urdu_subjects(self):
        calls = []

        def fake(system, user_text):
            calls.append((system, user_text))
            if "Urdu script" in system:
                return json.dumps({"weak_areas": [{"subject": "Urdu", "issue": "مسئلہ", "advice": "مشورہ"}],
                                   "subject_plans": [{"subject": "Urdu", "weeks": [{"title": "ہفتہ", "tasks": ["کام"]}], "checkpoint": "جانچ"}]})
            return json.dumps({"summary": "S", "weak_areas": [{"subject": "Urdu", "issue": "ENGLISH", "advice": "ENGLISH"},
                                                              {"subject": "Math", "issue": "m", "advice": "m"}]})
        with mock.patch("exams.ai.call_model", side_effect=fake):
            self.client.post(reverse("exams:ai", args=[self.exam.pk]), {"student": self.b.pk})
        self.assertEqual(len(calls), 3)
        urs_payload = json.loads(calls[2][1])
        self.assertEqual({x["subject"] for x in urs_payload["subjects"]}, {"Urdu", "Islamiat"})
        d = AISuggestion.objects.get(student=self.b).data
        by = {w["subject"]: w for w in d["weak_areas"]}
        self.assertEqual((by["Urdu"]["issue"], by["Urdu"]["lang"]), ("مسئلہ", "urs"))   # Urdu subject text comes from the Urdu call
        self.assertEqual(by["Math"]["issue"], "m")
        self.assertEqual(next(p for p in d["subject_plans"] if p["subject"] == "Urdu")["weeks"][0]["tasks"], ["کام"])

    @override_settings(AI_PROVIDER="gemini", GEMINI_API_KEY="g")
    def test_no_urdu_call_when_no_urdu_subject_is_weak(self):
        Mark.objects.filter(student=self.b, paper__in=(self.p_urdu, self.p_isl)).update(marks=95)
        calls = []
        with mock.patch("exams.ai.call_model", side_effect=lambda s, u: calls.append(s) or "{}"):
            self.client.post(reverse("exams:ai", args=[self.exam.pk]), {"student": self.b.pk})
        self.assertEqual(len(calls), 2)

    def test_pdf_renders_urdu_script(self):
        r = self.client.get(reverse("exams:report_card_pdf", args=[self.exam.pk, self.b.pk]))
        self.assertTrue(r.content.startswith(b"%PDF"))


class UrduScriptTests(Base):
    """The second language is real Urdu (Urdu script), never Roman Urdu."""

    def test_every_urdu_string_is_urdu_script_and_has_no_missing_keys(self):
        import re
        from exams.ai import TXT
        arabic = re.compile(r"[\u0600-\u06FF]")
        english_keys = set(TXT["en"])
        self.assertEqual(english_keys - set(TXT["ur"]), set())
        for key, val in TXT["ur"].items():
            if isinstance(val, str):
                self.assertRegex(val, arabic, key)                        # no key silently fell back to English
                self.assertFalse(re.search(r"\b(hai|hain|karo|rakho|ke liye|aur)\b", val), key)   # nor to Roman Urdu
            else:
                self.assertTrue(all(arabic.search(x) for x in val), key)

    def test_student_and_class_guidance_in_urdu_script(self):
        import re
        self.put(self.p_math, self.b, 20)
        self.put(self.p_eng, self.b, 10)
        self.put(self.p_math, self.a, 90)
        self.put(self.p_eng, self.a, 45)
        res = grading.compute(self.exam)
        g = ai.rule_student(insights.student_insights(res, grading.row_for(res, self.b.id)), "ur")
        for key in ("summary", "parent_note", "teacher_note", "motivation"):
            self.assertRegex(g[key], r"[\u0600-\u06FF]", key)
        c = ai.rule_class(insights.class_insights(res), "ur")
        self.assertRegex(c["summary"], r"[\u0600-\u06FF]")
        self.assertRegex(c["at_risk_note"], r"[\u0600-\u06FF]")
