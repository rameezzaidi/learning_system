import io
import random

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from academics.models import Course, Enrollment, SchoolClass, Subject
from accounts.models import User
from assessments.models import Assessment
from organization.models import Campus, Region

from . import services
from .models import BankQuestion


def mk(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


class Base(TestCase):
    def setUp(self):
        reg = Region.objects.create(name="S")
        self.c1 = Campus.objects.create(region=reg, name="A")
        self.cls = SchoolClass.objects.create(name="C8", section="A", campus=self.c1)
        self.t1, self.t2 = mk("t1", "teacher"), mk("t2", "teacher")
        self.course = Course.objects.create(school_class=self.cls, subject=Subject.objects.create(name="Maths"), teacher=self.t1)
        self.admin, self.student = mk("adm", "super_admin"), mk("s", "student")

    def add(self, n, level=2, topic="T"):
        for i in range(n):
            services.add_question(self.course, self.t1, "mcq", f"Q{level}-{i}", topic, level, "", ["a", "b", "c"], [1])


class ServiceTests(Base):
    def test_add_validation(self):
        f = lambda *a, **k: services.add_question(self.course, self.t1, *a, **k)
        self.assertTrue(f("mcq", "", options=["a", "b"], correct=[0])[1])
        self.assertTrue(f("mcq", "Q", options=["a"], correct=[0])[1])
        self.assertTrue(f("mcq", "Q", options=["a", "b"], correct=[])[1])
        self.assertTrue(f("mcq", "Q", options=["a", "b"], correct=[0, 1])[1])
        self.assertTrue(f("short", "Q", accepted=" ")[1])
        self.assertEqual(f("tf", "Q", options=[], correct=[1])[1], "")
        self.assertEqual(f("short", "Q", accepted="4|four")[1], "")
        self.assertEqual(BankQuestion.objects.count(), 2)

    def test_csv_import(self):
        csvtxt = ("topic,difficulty,question,a,b,c,d,correct,explanation\n"
                  "Add,easy,1+1?,1,2,3,4,B,because\n"
                  "Add,hard,2+2?,3,,4,,C,\n"          # blanks dropped, correct stays on '4'
                  "Add,medium,bad?,1,2,3,4,E,\n"
                  "Add,medium,,1,2,3,4,A,\n")
        n, errs = services.import_csv(self.course, self.t1, io.BytesIO(csvtxt.encode()))
        self.assertEqual(n, 2)
        self.assertEqual(len(errs), 2)
        q = BankQuestion.objects.get(text="2+2?")
        self.assertEqual((q.difficulty, [c.text for c in q.choices.filter(is_correct=True)]), (3, ["4"]))
        self.assertEqual(services.import_csv(self.course, self.t1, io.BytesIO(b"x,y\n1,2"))[0], 0)
        self.assertEqual(services.import_csv(self.course, self.t1, io.BytesIO(b"\xff\xfe"))[0], 0)

    def test_generate_copies_and_reports_shortage(self):
        self.add(3, 1)
        self.add(2, 3)
        a, notes = services.generate(self.course, self.t1, "Paper", easy=2, medium=1, hard=5, rng=random.Random(1))
        self.assertEqual(a.questions.count(), 4)  # 2 easy + 0 medium + 2 hard (all available)
        self.assertEqual(len(notes), 2)
        self.assertFalse(a.is_published)
        q = a.questions.first()
        self.assertEqual(q.choices.filter(is_correct=True).count(), 1)
        self.assertEqual(Assessment.objects.count(), 1)
        a2, notes2 = services.generate(self.course, self.t1, "None")
        self.assertIsNone(a2)

    def test_topic_filter(self):
        self.add(3, 2, "Alg")
        self.add(3, 2, "Geo")
        a, _ = services.generate(self.course, self.t1, "G", medium=3, topic="geo")
        self.assertTrue(all(q.text.startswith("Q2") for q in a.questions.all()))
        self.assertEqual(a.questions.count(), 3)


class ViewTests(Base):
    def test_access(self):
        url = reverse("bank:course", args=[self.course.pk])
        self.client.force_login(self.t1)
        self.assertEqual(self.client.get(url).status_code, 200)
        for u in (self.t2, self.student):
            self.client.force_login(u)
            self.assertIn(self.client.get(url).status_code, (403, 404), u.username)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_import_generate_delete_via_views(self):
        self.client.force_login(self.t1)
        url = reverse("bank:course", args=[self.course.pk])
        self.client.post(url, {"action": "add", "kind": "mcq", "text": "2+2?", "opt0": "4", "opt1": "5", "correct": "0", "difficulty": "1", "topic": "Add"})
        self.assertEqual(BankQuestion.objects.count(), 1)
        self.client.post(url, {"action": "add", "kind": "tf", "text": "Sky is blue", "tf": "true"})
        self.assertEqual(BankQuestion.objects.get(kind="tf").choices.get(is_correct=True).text, "True")
        f = SimpleUploadedFile("q.csv", b"topic,difficulty,question,a,b,c,d,correct,explanation\nX,1,Q?,a,b,,,A,\n")
        self.client.post(url, {"action": "import", "file": f})
        self.assertEqual(BankQuestion.objects.count(), 3)
        r = self.client.post(url, {"action": "generate", "title": "My quiz", "easy": "2", "medium": "0", "hard": "0"})
        a = Assessment.objects.get()
        self.assertRedirects(r, reverse("assessments:detail", args=[a.pk]), fetch_redirect_response=False)
        self.client.post(url, {"action": "delete", "id": BankQuestion.objects.first().pk})
        self.assertEqual(BankQuestion.objects.count(), 2)

    def test_lesson_planner_template_and_access(self):
        self.client.force_login(self.t1)
        r = self.client.post(reverse("insights:lesson_plan"), {"course": self.course.pk, "topic": "Fractions", "minutes": "45", "level": "mixed"})
        self.assertContains(r, "Fractions")
        self.assertContains(r, "Template")
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("insights:lesson_plan")).status_code, 403)
