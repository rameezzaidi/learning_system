from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Course, Enrollment, SchoolClass, Subject
from accounts.models import User

from . import grading
from .models import Answer, Assessment, Attempt, Choice, Question


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("adm", password="x", role="super_admin")
        cls.teacher = User.objects.create_user("t1", password="x", role="teacher")
        cls.other = User.objects.create_user("t2", password="x", role="teacher")
        cls.s1 = User.objects.create_user("s1", password="x", role="student", first_name="Ali")
        cls.s2 = User.objects.create_user("s2", password="x", role="student", first_name="Sara")
        cls.outsider = User.objects.create_user("s3", password="x", role="student")
        cls.parent = User.objects.create_user("p1", password="x", role="parent")
        cls.parent.children.add(cls.s1)
        cls.cls = SchoolClass.objects.create(name="Class 8", section="A")
        other_cls = SchoolClass.objects.create(name="Class 9", section="B")
        for s in (cls.s1, cls.s2):
            Enrollment.objects.create(student=s, school_class=cls.cls)
        Enrollment.objects.create(student=cls.outsider, school_class=other_cls)
        cls.course = Course.objects.create(school_class=cls.cls, subject=Subject.objects.create(name="Math"), teacher=cls.teacher)
        a = cls.a = Assessment.objects.create(course=cls.course, title="Q1", max_attempts=2, is_published=True)
        cls.q_mcq = Question.objects.create(assessment=a, kind="mcq", text="1+1?", points=2)
        cls.right = Choice.objects.create(question=cls.q_mcq, text="2", is_correct=True)
        cls.wrong = Choice.objects.create(question=cls.q_mcq, text="3")
        cls.q_short = Question.objects.create(assessment=a, kind="short", text="Capital of Pakistan", points=1, accepted="Islamabad|isb")
        cls.q_long = Question.objects.create(assessment=a, kind="long", text="Explain", points=5)

    def answer(self, user, choice=None, short="", long="Because", start=True):
        self.client.force_login(user)
        r = self.client.post(reverse("assessments:start", args=[self.a.pk]))
        att = Attempt.objects.filter(student=user).latest("id")
        self.assertRedirects(r, reverse("assessments:take", args=[att.pk]))
        data = {f"q{self.q_short.id}": short, f"q{self.q_long.id}": long}
        if choice:
            data[f"q{self.q_mcq.id}"] = choice.pk
        self.client.post(reverse("assessments:take", args=[att.pk]), data)
        att.refresh_from_db()
        return att


class GradingTests(Base):
    def test_auto_grade_and_pending_long(self):
        att = self.answer(self.s1, self.right, "  ISLAMABAD ")
        self.assertEqual(att.score, Decimal("3"))
        self.assertEqual(att.total, Decimal("8"))
        self.assertTrue(att.needs_review)

    def test_wrong_answers_score_zero(self):
        att = self.answer(self.s1, self.wrong, "karachi")
        self.assertEqual(att.score, 0)

    def test_manual_marking_finalises(self):
        att = self.answer(self.s1, self.right, "isb")
        self.client.force_login(self.teacher)
        self.client.post(reverse("assessments:review", args=[att.pk]), {f"pts{self.q_long.id}": "4", f"fb{self.q_long.id}": "Good"})
        att.refresh_from_db()
        self.assertFalse(att.needs_review)
        self.assertEqual(att.score, Decimal("7"))
        self.assertEqual(att.percent, 87.5)

    def test_marks_capped_at_max(self):
        att = self.answer(self.s1, self.right, "isb")
        self.client.force_login(self.teacher)
        self.client.post(reverse("assessments:review", args=[att.pk]), {f"pts{self.q_long.id}": "99"})
        att.refresh_from_db()
        self.assertEqual(att.score, Decimal("8"))

    def test_letter(self):
        self.assertEqual([grading.letter(x) for x in (95, 85, 75, 65, 55, 10, None)], ["A+", "A", "B", "C", "D", "F", "—"])

    def test_attempt_limit_and_best(self):
        self.answer(self.s1, self.wrong, "x")
        self.answer(self.s1, self.right, "isb")
        self.client.post(reverse("assessments:start", args=[self.a.pk]))
        self.assertEqual(Attempt.objects.filter(student=self.s1).count(), 2)  # third refused
        self.assertEqual(grading.best_attempt(self.a, self.s1).score, Decimal("3"))


class TimerTests(Base):
    def test_expired_attempt_ignores_late_answers(self):
        self.a.duration_minutes = 5
        self.a.save()
        self.client.force_login(self.s1)
        self.client.post(reverse("assessments:start", args=[self.a.pk]))
        att = Attempt.objects.get(student=self.s1)
        Attempt.objects.filter(pk=att.pk).update(started_at=timezone.now() - __import__("datetime").timedelta(minutes=10))
        self.client.post(reverse("assessments:take", args=[att.pk]), {f"q{self.q_mcq.id}": self.right.pk})
        att.refresh_from_db()
        self.assertTrue(att.submitted)
        self.assertEqual(att.score, 0)


class AccessTests(Base):
    def test_unpublished_hidden_from_student(self):
        self.a.is_published = False
        self.a.save()
        self.client.force_login(self.s1)
        self.assertEqual(self.client.post(reverse("assessments:start", args=[self.a.pk])).status_code, 403)

    def test_student_in_other_class_blocked(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(reverse("assessments:start", args=[self.a.pk])).status_code, 403)

    def test_other_teacher_cannot_manage(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("assessments:detail", args=[self.a.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("assessments:gradebook", args=[self.course.pk])).status_code, 403)

    def test_student_cannot_open_teacher_pages(self):
        self.client.force_login(self.s1)
        for name, arg in (("detail", self.a.pk), ("results", self.a.pk)):
            self.assertEqual(self.client.get(reverse(f"assessments:{name}", args=[arg])).status_code, 403)

    def test_result_visibility(self):
        att = self.answer(self.s1, self.right, "isb")
        url = reverse("assessments:result", args=[att.pk])
        for u, code in ((self.s1, 200), (self.parent, 200), (self.teacher, 200), (self.admin, 200), (self.s2, 403), (self.other, 403)):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, code, u.username)

    def test_cannot_take_someone_elses_attempt(self):
        att = self.answer(self.s1, self.right, "isb")
        self.client.force_login(self.s2)
        self.assertEqual(self.client.get(reverse("assessments:take", args=[att.pk])).status_code, 404)

    def test_answers_hidden_when_disabled(self):
        self.a.show_answers = False
        self.a.save()
        att = self.answer(self.s1, self.wrong, "x")
        self.client.force_login(self.s1)
        r = self.client.get(reverse("assessments:result", args=[att.pk]))
        self.assertNotContains(r, "Accepted:")
        self.assertNotContains(r, "✓")


class BuilderTests(Base):
    def setUp(self):
        self.client.force_login(self.teacher)

    def test_create_mcq_question(self):
        r = self.client.post(reverse("assessments:question_create", args=[self.a.pk]), {
            "kind": "mcq", "text": "Pick", "points": "2", "choice1": "a", "choice2": "b", "choice3": "", "choice4": "", "correct": "2"})
        self.assertEqual(r.status_code, 302)
        q = Question.objects.get(text="Pick")
        self.assertEqual([(c.text, c.is_correct) for c in q.choices.all()], [("a", False), ("b", True)])

    def test_mcq_validation(self):
        r = self.client.post(reverse("assessments:question_create", args=[self.a.pk]), {
            "kind": "mcq", "text": "Pick", "points": "2", "choice1": "a", "correct": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Question.objects.filter(text="Pick").exists())

    def test_tf_and_short(self):
        self.client.post(reverse("assessments:question_create", args=[self.a.pk]), {"kind": "tf", "text": "T?", "points": "1", "tf_answer": "false"})
        self.assertTrue(Question.objects.get(text="T?").choices.get(text="False").is_correct)
        self.client.post(reverse("assessments:question_create", args=[self.a.pk]), {"kind": "short", "text": "S?", "points": "1", "accepted": "x|y"})
        self.assertEqual(Question.objects.get(text="S?").accepted, "x|y")

    def test_publish_requires_questions(self):
        empty = Assessment.objects.create(course=self.course, title="Empty")
        self.client.post(reverse("assessments:toggle", args=[empty.pk]))
        empty.refresh_from_db()
        self.assertFalse(empty.is_published)
        self.client.post(reverse("assessments:toggle", args=[self.a.pk]))
        self.a.refresh_from_db()
        self.assertFalse(self.a.is_published)

    def test_create_assessment_and_edit_question_replaces_choices(self):
        r = self.client.post(reverse("assessments:create", args=[self.course.pk]), {
            "title": "New", "kind": "test", "duration_minutes": 0, "max_attempts": 1})
        self.assertEqual(r.status_code, 302)
        self.client.post(reverse("assessments:question_edit", args=[self.q_mcq.pk]), {
            "kind": "mcq", "text": "1+1?", "points": "2", "choice1": "2", "choice2": "4", "correct": "1"})
        self.assertEqual(self.q_mcq.choices.count(), 2)


class GradebookTests(Base):
    def test_gradebook_rows_and_csv(self):
        self.answer(self.s1, self.right, "isb")
        self.client.force_login(self.teacher)
        r = self.client.get(reverse("assessments:gradebook", args=[self.course.pk]))
        self.assertEqual(r.status_code, 200)
        rows = {x["student"].username: x for x in r.context["rows"]}
        self.assertEqual(rows["s1"]["avg"], 37.5)
        self.assertIsNone(rows["s2"]["avg"])
        csv = self.client.get(reverse("assessments:gradebook_csv", args=[self.course.pk])).content.decode("utf-8-sig")
        self.assertIn("Ali", csv)
        self.assertIn("Q1", csv)

    def test_student_progress_and_parent_view(self):
        self.answer(self.s1, self.right, "isb")
        self.client.force_login(self.s1)
        self.assertContains(self.client.get(reverse("assessments:progress")), "Q1")
        self.client.force_login(self.parent)
        r = self.client.get(reverse("academics:child_progress", args=[self.s1.pk]))
        self.assertContains(r, "Assessment results")

    def test_pages_render_for_each_role(self):
        for u in (self.admin, self.teacher, self.s1):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("assessments:list")).status_code, 200)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("assessments:gradebook_index")).status_code, 200)
        self.assertEqual(self.client.get(reverse("academics:course_detail", args=[self.course.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("assessments:detail", args=[self.a.pk])).status_code, 200)


class SubjectEditorTests(Base):
    """The question editor and the student pages adapt to the subject (Maths / English / Urdu & Islamiat)."""

    def make(self, subject):
        course = Course.objects.create(school_class=self.cls, subject=Subject.objects.get_or_create(name=subject)[0], teacher=self.teacher)
        a = Assessment.objects.create(course=course, title=f"{subject} quiz", is_published=True, max_attempts=3)
        Question.objects.create(assessment=a, kind="short", text="Solve $x^{2}=4$", accepted="2")
        return a

    def editor(self, a):
        self.client.force_login(self.teacher)
        return self.client.get(reverse("assessments:question_create", args=[a.pk])).content.decode()

    def test_editor_kind_follows_subject(self):
        for subject, kind, label in (("Mathematics", "math", "Maths editor"), ("English", "english", "English editor"),
                                      ("Urdu", "urdu", "Urdu editor"), ("Islamiat", "urdu", "Urdu editor"), ("Science", "general", "Standard editor")):
            body = self.editor(self.make(subject))
            self.assertIn(f'data-kind="{kind}"', body, subject)
            self.assertIn(label, body, subject)
            self.assertIn("js/editor.js", body)

    def test_katex_only_for_maths(self):
        self.assertIn("katex.min.js", self.editor(self.make("Algebra")))
        self.assertNotIn("katex.min.js", self.editor(self.make("English")))

    def test_editor_fields_are_marked(self):
        body = self.editor(self.make("Maths"))
        self.assertEqual(body.count('data-ed="1"'), 7)      # text, 4 options, explanation, accepted answers

    def test_student_pages_get_subject_class_and_math_rendering(self):
        math, eng, urdu = self.make("Maths"), self.make("English"), self.make("Urdu")
        self.client.force_login(self.s1)
        for a, kind, katex in ((math, "math", True), (eng, "english", False), (urdu, "urdu", False)):
            r = self.client.post(reverse("assessments:start", args=[a.pk]))
            att = Attempt.objects.filter(student=self.s1, assessment=a).latest("id")
            body = self.client.get(reverse("assessments:take", args=[att.pk])).content.decode()
            self.assertIn(f'classList.add("kind-{kind}")', body)
            self.assertEqual("katex.min.js" in body, katex, kind)
            self.assertEqual(r.status_code, 302)

    def test_math_text_is_still_escaped(self):
        a = self.make("Maths")
        Question.objects.create(assessment=a, kind="short", text="<script>alert(1)</script> $a<b$", accepted="x")
        self.client.force_login(self.s1)
        self.client.post(reverse("assessments:start", args=[a.pk]))
        att = Attempt.objects.filter(student=self.s1, assessment=a).latest("id")
        body = self.client.get(reverse("assessments:take", args=[att.pk])).content.decode()
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)
