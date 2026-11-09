from datetime import date

from django.test import TestCase
from django.urls import reverse

from academics.models import Course, Enrollment, SchoolClass, Subject
from accounts.models import User
from core.models import AuditLog, Notification
from organization.models import Campus, Region, StudentProfile

from .models import Handover, Topic
from . import services


def mk(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


class Base(TestCase):
    def setUp(self):
        reg = Region.objects.create(name="South")
        self.c1, self.c2 = Campus.objects.create(region=reg, name="Alpha"), Campus.objects.create(region=reg, name="Beta")
        self.subj = Subject.objects.create(name="Maths")
        self.cls1 = SchoolClass.objects.create(name="Class 8", section="A", campus=self.c1)
        self.cls2 = SchoolClass.objects.create(name="Class 8", section="B", campus=self.c2)
        self.t1, self.t2, self.t3 = mk("t1", "teacher"), mk("t2", "teacher"), mk("t3", "teacher")
        self.course1 = Course.objects.create(school_class=self.cls1, subject=self.subj, teacher=self.t1)
        self.course2 = Course.objects.create(school_class=self.cls2, subject=self.subj, teacher=self.t2)
        self.admin = mk("adm", "super_admin")
        self.prin = mk("prin", "principal", campus=self.c1)
        self.head = mk("head", "head_office")
        self.stu = mk("stu", "student")
        Enrollment.objects.create(student=self.stu, school_class=self.cls1)
        StudentProfile.objects.create(user=self.stu, campus=self.c1)
        for i in range(4):
            Topic.objects.create(course=self.course1, chapter="Fractions", title=f"T{i}", position=i)
        for i in range(4):
            Topic.objects.create(course=self.course2, chapter="Fractions", title=f"T{i}", position=i)

    def login(self, u):
        self.client.force_login(u)


class OutlineTests(Base):
    def test_teacher_marks_topic_taught_and_coverage_updates(self):
        self.login(self.t1)
        t = self.course1.topics.first()
        self.assertEqual(self.client.post(reverse("curriculum:topic_toggle", args=[t.pk]), {"note": "done in class"}).status_code, 302)
        t.refresh_from_db()
        self.assertTrue(t.is_covered)
        self.assertEqual(t.covered_by, self.t1)
        self.assertEqual(services.coverage(self.course1)["pct"], 25)
        self.assertTrue(AuditLog.objects.filter(action="curriculum.covered").exists())
        self.client.post(reverse("curriculum:topic_toggle", args=[t.pk]))
        t.refresh_from_db()
        self.assertFalse(t.is_covered)

    def test_other_teacher_cannot_edit(self):
        self.login(self.t3)
        t = self.course1.topics.first()
        self.assertEqual(self.client.post(reverse("curriculum:topic_toggle", args=[t.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("curriculum:outline", args=[self.course1.pk])).status_code, 404)

    def test_students_blocked(self):
        self.login(self.stu)
        self.assertEqual(self.client.get(reverse("curriculum:index")).status_code, 403)

    def test_bulk_add_formats(self):
        self.login(self.t1)
        self.client.post(reverse("curriculum:topics_add", args=[self.course1.pk]), {
            "lines": "Unit 1 | Decimals | Place value | Read decimals\nDecimals | Rounding\nRatios\n\n | | "})
        ts = {t.title: t for t in self.course1.topics.all()}
        self.assertEqual(ts["Place value"].unit, "Unit 1")
        self.assertEqual(ts["Place value"].outcome, "Read decimals")
        self.assertEqual(ts["Rounding"].chapter, "Decimals")
        self.assertEqual(ts["Ratios"].chapter, "")
        self.assertEqual(len(ts), 7)

    def test_copy_outline_starts_uncovered(self):
        c = Course.objects.create(school_class=SchoolClass.objects.create(name="Class 9", section="A", campus=self.c1), subject=self.subj, teacher=self.t1)
        self.course1.topics.update(is_covered=True)
        self.login(self.t1)
        self.client.post(reverse("curriculum:topics_copy", args=[c.pk]), {"source": self.course1.pk})
        self.assertEqual(c.topics.count(), 4)
        self.assertEqual(c.topics.filter(is_covered=True).count(), 0)

    def test_principal_scope(self):
        self.login(self.prin)
        self.assertEqual(self.client.get(reverse("curriculum:outline", args=[self.course1.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("curriculum:outline", args=[self.course2.pk])).status_code, 404)


class MonitorTests(Base):
    def test_gap_between_campuses_detected_and_scoped(self):
        self.course1.topics.update(is_covered=True, covered_on=date.today())  # 100%
        self.login(self.head)
        r = self.client.get(reverse("curriculum:monitor"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["gaps"]), 1)
        self.assertEqual(r.context["gaps"][0]["spread"], 100)
        self.login(self.prin)
        r = self.client.get(reverse("curriculum:monitor"))
        self.assertEqual({x["campus"] for x in r.context["rows"]}, {"Alpha"})
        self.assertEqual(r.context["gaps"], [])

    def test_stale_flag_and_csv(self):
        Topic.objects.filter(pk=self.course1.topics.first().pk).update(is_covered=True, covered_on=date(2020, 1, 1))
        self.login(self.head)
        r = self.client.get(reverse("curriculum:monitor"))
        self.assertTrue(any(x["stale"] for x in r.context["rows"]))
        csv = self.client.get(reverse("curriculum:monitor") + "?format=csv")
        self.assertEqual(csv.status_code, 200)
        self.assertIn("Coverage %", csv.content.decode())

    def test_teacher_blocked(self):
        self.login(self.t1)
        self.assertEqual(self.client.get(reverse("curriculum:monitor")).status_code, 403)


class HandoverTests(Base):
    def test_changing_teacher_creates_handover_with_snapshot_and_notifies(self):
        for t in list(self.course1.topics.all())[:2]:
            t.is_covered, t.covered_on = True, date(2026, 10, 1)
            t.save()
        self.course1.teacher = self.t3
        self.course1.save()
        h = Handover.objects.get(course=self.course1)
        self.assertEqual((h.from_teacher, h.to_teacher, h.kind), (self.t1, self.t3, "transfer"))
        self.assertEqual(h.snapshot["done"], 2)
        self.assertEqual(h.snapshot["last_title"], "T1")
        self.assertEqual(len(h.snapshot["next_topics"]), 2)
        self.assertTrue(Notification.objects.filter(user=self.t3, kind="handover").exists())
        self.assertTrue(Notification.objects.filter(user=self.prin, kind="handover").exists())
        self.assertFalse(Notification.objects.filter(user=self.head, kind="handover").exists())

    def test_no_handover_when_teacher_unchanged_or_on_create(self):
        self.course1.description = "x"
        self.course1.save()
        self.assertEqual(Handover.objects.count(), 0)

    def test_new_handover_supersedes_open_one(self):
        self.course1.teacher = self.t3
        self.course1.save()
        self.course1.teacher = self.t2
        self.course1.save()
        self.assertEqual(Handover.objects.filter(course=self.course1, status="closed").count(), 1)
        self.assertEqual(Handover.objects.filter(course=self.course1).exclude(status="closed").count(), 1)

    def test_acknowledge_only_by_receiver(self):
        self.course1.teacher = self.t3
        self.course1.save()
        h = Handover.objects.get(course=self.course1)
        self.login(self.t1)
        self.assertEqual(self.client.post(reverse("curriculum:handover_ack", args=[h.pk])).status_code, 403)
        self.login(self.t3)
        self.assertEqual(self.client.get(reverse("curriculum:handover_detail", args=[h.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("curriculum:handover_ack", args=[h.pk]), {"note": "got it"}).status_code, 302)
        h.refresh_from_db()
        self.assertEqual(h.status, "acknowledged")
        self.assertIsNotNone(h.acknowledged_at)

    def test_unrelated_teacher_and_other_campus_principal_cannot_view(self):
        self.course1.teacher = self.t3
        self.course1.save()
        h = Handover.objects.get(course=self.course1)
        self.login(self.t2)
        self.assertEqual(self.client.get(reverse("curriculum:handover_detail", args=[h.pk])).status_code, 404)
        other = mk("prin2", "principal", campus=self.c2)
        self.login(other)
        self.assertEqual(self.client.get(reverse("curriculum:handover_detail", args=[h.pk])).status_code, 404)
        self.login(self.prin)
        self.assertEqual(self.client.get(reverse("curriculum:handover_detail", args=[h.pk])).status_code, 200)

    def test_absence_cover_gives_substitute_edit_rights_until_closed(self):
        self.login(self.t1)
        r = self.client.post(reverse("curriculum:handover_new", args=[self.course1.pk]), {"kind": "absence", "to": self.t3.pk, "reason": "Leave"})
        self.assertEqual(r.status_code, 302)
        h = Handover.objects.get(course=self.course1)
        self.assertEqual(h.kind, "absence")
        self.course1.refresh_from_db()
        self.assertEqual(self.course1.teacher, self.t1)  # still the course teacher
        t = self.course1.topics.first()
        self.login(self.t3)
        self.assertEqual(self.client.post(reverse("curriculum:topic_toggle", args=[t.pk])).status_code, 302)
        self.login(self.t1)
        self.client.post(reverse("curriculum:handover_close", args=[h.pk]))
        self.login(self.t3)
        self.assertEqual(self.client.post(reverse("curriculum:topic_toggle", args=[t.pk])).status_code, 403)

    def test_transfer_form_reassigns_course(self):
        self.login(self.principal_head())
        self.client.post(reverse("curriculum:handover_new", args=[self.course1.pk]), {"kind": "transfer", "to": self.t3.pk, "reason": "Resigned"})
        self.course1.refresh_from_db()
        self.assertEqual(self.course1.teacher, self.t3)
        self.assertEqual(Handover.objects.filter(course=self.course1).count(), 1)
        self.assertEqual(Handover.objects.get(course=self.course1).reason, "Resigned")

    def principal_head(self):
        return self.prin

    def test_other_teacher_cannot_create_handover(self):
        self.login(self.t2)
        self.assertEqual(self.client.get(reverse("curriculum:handover_new", args=[self.course1.pk])).status_code, 404)

    def test_pages_render(self):
        self.course1.teacher = self.t3
        self.course1.save()
        for u in (self.admin, self.head, self.prin, self.t3):
            self.login(u)
            self.assertEqual(self.client.get(reverse("curriculum:handover_list")).status_code, 200)
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("curriculum:index")).status_code, 200)
