from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Course, Enrollment, SchoolClass, Subject
from accounts.models import User
from attendance.models import AttendanceRecord
from fees.models import LedgerEntry
from organization.models import Campus, Region, StudentProfile

from . import services


def mk(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


class Base(TestCase):
    def setUp(self):
        reg = Region.objects.create(name="South")
        self.c1, self.c2 = Campus.objects.create(region=reg, name="Alpha"), Campus.objects.create(region=reg, name="Beta")
        self.cls = SchoolClass.objects.create(name="C8", section="A", campus=self.c1)
        self.cls2 = SchoolClass.objects.create(name="C8", section="B", campus=self.c2)
        self.t1, self.t2 = mk("t1", "teacher", campus=self.c1), mk("t2", "teacher", campus=self.c2)
        self.maths = Course.objects.create(school_class=self.cls, subject=Subject.objects.create(name="Maths"), teacher=self.t1)
        Course.objects.create(school_class=self.cls2, subject=Subject.objects.get(name="Maths"), teacher=self.t2)
        self.s1, self.s2 = mk("s1", "student"), mk("s2", "student")
        for s, cl, c in ((self.s1, self.cls, self.c1), (self.s2, self.cls2, self.c2)):
            Enrollment.objects.create(student=s, school_class=cl)
            StudentProfile.objects.create(user=s, campus=c, admission_no=s.username)
        self.parent, self.parent2 = mk("par", "parent"), mk("par2", "parent")
        self.parent.children.set([self.s1])
        self.parent2.children.set([self.s2])
        self.admin, self.head = mk("adm", "super_admin"), mk("head", "head_office")
        self.prin, self.prin2 = mk("prin", "principal", campus=self.c1), mk("prin2", "principal", campus=self.c2)


class ProfileTests(Base):
    def test_access_matrix(self):
        url = reverse("insights:dna", args=[self.s1.pk])
        for u in (self.admin, self.head, self.prin, self.t1, self.s1, self.parent):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 200, u.username)
        for u in (self.prin2, self.t2, self.s2, self.parent2):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.username)

    def test_profile_flags_focus_and_attendance(self):
        from assessments.models import Assessment, Attempt
        a = Assessment.objects.create(course=self.maths, title="Q", is_published=True)
        Attempt.objects.create(assessment=a, student=self.s1, submitted_at=timezone.now(), score=Decimal("2"), total=Decimal("10"))
        for i in range(1, 9):
            AttendanceRecord.objects.create(student=self.s1, school_class=self.cls, date=timezone.localdate() - timedelta(days=i), status="absent" if i < 5 else "present")
        p = services.learning_profile(self.s1)
        self.assertEqual(p["focus"], ["Maths"])
        self.assertTrue(any("Attendance" in s for s in p["steps"]), (p["att"], p["steps"]))
        self.assertIn("Maths", p["remark"])
        self.client.force_login(self.s1)
        self.assertNotContains(self.client.get(reverse("insights:dna", args=[self.s1.pk])), "Draft remark")  # staff only

    def test_empty_profile_is_honest(self):
        p = services.learning_profile(self.s2)
        self.assertIn("not have enough", p["remark"])
        self.assertTrue(p["steps"])


class PlannerTests(Base):
    def test_rule_plan_and_ai_fallback(self):
        plan = services.lesson_plan("Maths", "C8", "Fractions", 40, "mixed")
        self.assertEqual(plan["source"], "template")
        self.assertTrue(all(plan[k] for k in services.PLAN_KEYS))
        from exams import ai
        good = '{"objectives":["a","b","c"],"starter":"s","main":["m1","m2"],"check":"c","differentiation":["d1","d2"],"homework":"h","resources":["r"]}'
        with mock.patch.object(ai, "enabled", return_value=True), mock.patch.object(ai, "call_model", return_value=good):
            self.assertEqual(services.lesson_plan("Maths", "C8", "Fractions", 40, "mixed")["source"], "ai")
        with mock.patch.object(ai, "enabled", return_value=True), mock.patch.object(ai, "call_model", return_value="not json"):
            self.assertEqual(services.lesson_plan("Maths", "C8", "Fractions", 40, "mixed")["source"], "template")
        with mock.patch.object(ai, "enabled", return_value=True), mock.patch.object(ai, "call_model", side_effect=RuntimeError("down")):
            self.assertEqual(services.lesson_plan("Maths", "C8", "Fractions", 40, "mixed")["source"], "template")
        with mock.patch.object(ai, "enabled", return_value=True), mock.patch.object(ai, "call_model", return_value='{"objectives":"x"}'):
            self.assertEqual(services.lesson_plan("Maths", "C8", "Fractions", 40, "mixed")["source"], "template")

    def test_no_personal_data_sent(self):
        from exams import ai
        seen = []
        with mock.patch.object(ai, "enabled", return_value=True), mock.patch.object(ai, "call_model", side_effect=lambda s, u: seen.append(u) or "x"):
            services.lesson_plan("Maths", "C8", "Fractions", 40, "mixed")
        self.assertNotIn("t1", seen[0].lower().split("topic")[0])


class ExecutiveTests(Base):
    def test_numbers_scope_and_csv(self):
        today = timezone.localdate()
        for i in range(1, 5):
            AttendanceRecord.objects.create(student=self.s1, school_class=self.cls, date=today - timedelta(days=i), status="present" if i < 4 else "absent")
        LedgerEntry.objects.create(student=self.s1, kind="monthly", month=today.replace(day=1), entry_date=today, debit=Decimal("1000"), description="m")
        LedgerEntry.objects.create(student=self.s1, kind="payment", month=today.replace(day=1), entry_date=today, credit=Decimal("500"), description="p")
        rows = {r["campus"].name: r for r in services.executive(self.head)}
        self.assertEqual(rows["Alpha"]["attendance"], 75.0)
        self.assertEqual((rows["Alpha"]["billed"], rows["Alpha"]["collection"]), (1000, 50.0))
        self.assertEqual(rows["Beta"]["billed"], 0)
        self.assertEqual([r["campus"].name for r in services.executive(self.prin)], ["Alpha"])

    def test_access_and_csv_safety(self):
        self.c1.name = "=cmd"
        self.c1.save()
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("insights:executive")).status_code, 200)
        body = self.client.get(reverse("insights:executive") + "?format=csv").content.decode("utf-8-sig")
        self.assertIn("'=cmd", body)
        for u in (self.t1, self.s1, self.parent):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("insights:executive")).status_code, 403, u.username)
