from datetime import date, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Course, Enrollment, SchoolClass, Subject
from accounts.models import User
from attendance.models import StaffAttendance
from core.models import AuditLog, Notification
from organization.models import Campus, Region, StudentProfile

from . import services
from .models import CalendarEvent, Period, Slot, Substitution, Term


def mk(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


class Base(TestCase):
    def setUp(self):
        reg = Region.objects.create(name="South")
        self.c1, self.c2 = Campus.objects.create(region=reg, name="Alpha"), Campus.objects.create(region=reg, name="Beta")
        self.cls = SchoolClass.objects.create(name="Class 8", section="A", campus=self.c1)
        self.cls_b = SchoolClass.objects.create(name="Class 9", section="A", campus=self.c1)
        self.cls2 = SchoolClass.objects.create(name="Class 8", section="B", campus=self.c2)
        self.maths, self.eng, self.sci = (Subject.objects.create(name=n) for n in ("Maths", "English", "Science"))
        self.t1 = mk("t1", "teacher", campus=self.c1)
        self.t2 = mk("t2", "teacher", campus=self.c1)
        self.t3 = mk("t3", "teacher", campus=self.c1)
        self.t_other = mk("tx", "teacher", campus=self.c2)
        self.m8 = Course.objects.create(school_class=self.cls, subject=self.maths, teacher=self.t1)
        self.e8 = Course.objects.create(school_class=self.cls, subject=self.eng, teacher=self.t2)
        self.m9 = Course.objects.create(school_class=self.cls_b, subject=self.maths, teacher=self.t1)  # same teacher, other class
        self.s_other = Course.objects.create(school_class=self.cls2, subject=self.sci, teacher=self.t_other)
        self.p1 = Period.objects.create(name="P1", start_time=time(8), end_time=time(8, 45), order=1)
        self.p2 = Period.objects.create(name="P2", start_time=time(8, 45), end_time=time(9, 30), order=2)
        self.brk = Period.objects.create(name="Break", start_time=time(9, 30), end_time=time(9, 50), order=3, is_break=True)
        self.s1, self.s2 = mk("s1", "student"), mk("s2", "student")
        for s, cl, c in ((self.s1, self.cls, self.c1), (self.s2, self.cls2, self.c2)):
            Enrollment.objects.create(student=s, school_class=cl)
            StudentProfile.objects.create(user=s, campus=c, admission_no=s.username)
        self.parent = mk("par", "parent")
        self.parent.children.set([self.s1])
        self.admin, self.head = mk("adm", "super_admin"), mk("head", "head_office")
        self.prin = mk("prin", "principal", campus=self.c1)
        self.reg = mk("regd", "regional_director", region=reg)


class GridTests(Base):
    def test_save_and_clash(self):
        self.assertEqual(services.save_grid(self.cls, {(0, self.p1.pk): self.m8.pk, (0, self.p2.pk): self.e8.pk}), [])
        self.assertEqual(Slot.objects.filter(school_class=self.cls).count(), 2)
        errs = services.save_grid(self.cls_b, {(0, self.p1.pk): self.m9.pk})  # t1 already teaches Class 8 A Monday P1
        self.assertEqual(len(errs), 1)
        self.assertIn("already teaches", errs[0])
        self.assertEqual(Slot.objects.filter(school_class=self.cls_b).count(), 0)

    def test_all_or_nothing_and_replace(self):
        services.save_grid(self.cls, {(0, self.p1.pk): self.m8.pk})
        errs = services.save_grid(self.cls, {(0, self.p1.pk): self.e8.pk, (1, self.p1.pk): self.s_other.pk})  # 2nd: wrong class
        self.assertTrue(errs)
        self.assertEqual(Slot.objects.get().course, self.m8)  # untouched
        self.assertEqual(services.save_grid(self.cls, {(0, self.p1.pk): self.e8.pk}), [])
        self.assertEqual(Slot.objects.get().course, self.e8)
        self.assertEqual(services.save_grid(self.cls, {}), [])
        self.assertEqual(Slot.objects.count(), 0)

    def test_break_and_bad_weekday_ignored(self):
        services.save_grid(self.cls, {(0, self.brk.pk): self.m8.pk, (9, self.p1.pk): self.m8.pk})
        self.assertEqual(Slot.objects.count(), 0)

    def test_db_unique_slot(self):
        Slot.objects.create(school_class=self.cls, weekday=0, period=self.p1, course=self.m8)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Slot.objects.create(school_class=self.cls, weekday=0, period=self.p1, course=self.e8)

    def test_grid_shape_hides_empty_saturday(self):
        g = services.class_grid(self.cls)
        self.assertEqual(len(g["days"]), 5)
        self.assertEqual(len(services.class_grid(self.cls, editing=True)["days"]), 6)


class AccessTests(Base):
    def setUp(self):
        super().setUp()
        services.save_grid(self.cls, {(0, self.p1.pk): self.m8.pk})

    def test_view_scope(self):
        url = reverse("timetable:class", args=[self.cls.pk])
        ok = [self.admin, self.head, self.prin, self.reg, self.t1, self.s1, self.parent]
        no = [self.s2, self.t_other, self.t3]
        for u in ok:
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 200, u.username)
        for u in no:
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.username)
        self.client.force_login(mk("prin2", "principal", campus=self.c2))
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_student_and_parent_index_redirect(self):
        for u in (self.s1, self.parent):
            self.client.force_login(u)
            r = self.client.get(reverse("timetable:index"))
            self.assertRedirects(r, reverse("timetable:class", args=[self.cls.pk]))

    def test_edit_permissions(self):
        url = reverse("timetable:edit", args=[self.cls.pk])
        for u, code in ((self.admin, 200), (self.head, 200), (self.prin, 200), (self.reg, 403), (self.t1, 403), (self.s1, 403), (self.parent, 403)):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, code, u.username)
        self.client.force_login(mk("prin2", "principal", campus=self.c2))
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_edit_post_saves_and_reports_clash(self):
        self.client.force_login(self.prin)
        url = reverse("timetable:edit", args=[self.cls_b.pk])
        r = self.client.post(url, {f"c_0_{self.p1.pk}": self.m9.pk})  # t1 clash on Monday P1
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already teaches")
        self.assertEqual(Slot.objects.filter(school_class=self.cls_b).count(), 0)
        r = self.client.post(url, {f"c_1_{self.p1.pk}": self.m9.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Slot.objects.filter(school_class=self.cls_b).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="timetable.save").exists())

    def test_my_timetable_teacher_only(self):
        self.client.force_login(self.t1)
        self.assertContains(self.client.get(reverse("timetable:mine")), "Maths")
        self.client.force_login(self.s1)
        self.assertEqual(self.client.get(reverse("timetable:mine")).status_code, 403)


class PeriodTests(Base):
    def test_add_validate_delete(self):
        self.client.force_login(self.prin)
        url = reverse("timetable:periods")
        self.client.post(url, {"action": "add", "name": "P3", "start_time": "10:00", "end_time": "09:00", "order": 4})
        self.client.post(url, {"action": "add", "name": "dup", "start_time": "10:00", "end_time": "11:00", "order": 1})
        self.assertEqual(Period.objects.count(), 3)
        self.client.post(url, {"action": "add", "name": "P3", "start_time": "10:00", "end_time": "10:45", "order": 4})
        self.assertEqual(Period.objects.count(), 4)
        self.client.post(url, {"action": "delete", "period": self.p2.pk})
        self.assertFalse(Period.objects.filter(pk=self.p2.pk).exists())
        self.client.force_login(self.t1)
        self.assertEqual(self.client.get(url).status_code, 403)


class SubstitutionTests(Base):
    def setUp(self):
        super().setUp()
        services.save_grid(self.cls, {(0, self.p1.pk): self.m8.pk})  # t1 teaches Monday P1
        services.save_grid(self.cls2, {(0, self.p1.pk): self.s_other.pk})
        d = timezone.localdate()
        self.monday = d - timedelta(days=d.weekday())  # a Monday
        self.slot = Slot.objects.get(school_class=self.cls)

    def absent(self, teacher, day=None):
        StaffAttendance.objects.create(teacher=teacher, date=day or self.monday, status="absent")

    def test_cover_rows_and_free_teachers(self):
        self.absent(self.t1)
        teachers = [self.t1, self.t2, self.t3]
        rows = services.cover_rows(self.monday, teachers)
        self.assertEqual([r["slot"] for r in rows], [self.slot])
        free = services.free_teachers(self.monday, self.p1.pk, teachers)
        self.assertEqual({t.pk for t in free}, {self.t2.pk, self.t3.pk})  # t1 is absent
        # t2 teaches nothing Monday P1; give t2 a lesson then t2 is busy
        Slot.objects.create(school_class=self.cls_b, weekday=0, period=self.p1, course=Course.objects.create(school_class=self.cls_b, subject=self.eng, teacher=self.t2))
        free = services.free_teachers(self.monday, self.p1.pk, teachers)
        self.assertEqual({t.pk for t in free}, {self.t3.pk})

    def test_assign_via_view_notifies_and_blocks_busy(self):
        self.absent(self.t1)
        self.client.force_login(self.prin)
        url = reverse("timetable:substitutions")
        self.client.post(url, {"date": self.monday.isoformat(), "slot": self.slot.pk, "substitute": self.t3.pk, "reason": "sick"})
        self.assertEqual(Substitution.objects.get().substitute, self.t3)
        self.assertTrue(Notification.objects.filter(user=self.t3, kind="timetable").exists())
        # a second slot's cover cannot reuse t3 in the same period
        err = services.assign_substitute(Slot.objects.get(school_class=self.cls2), self.monday, self.t3, "", self.prin)
        self.assertIn("not free", err)
        self.client.post(url, {"date": self.monday.isoformat(), "slot": self.slot.pk, "action": "remove"})
        self.assertEqual(Substitution.objects.count(), 0)

    def test_wrong_weekday_rejected(self):
        self.assertTrue(services.assign_substitute(self.slot, self.monday + timedelta(days=1), self.t3, "", self.prin))

    def test_out_of_scope_slot_is_404_and_roles(self):
        self.absent(self.t_other)
        self.client.force_login(self.prin)  # campus Alpha; t_other is Beta
        other_slot = Slot.objects.get(school_class=self.cls2)
        r = self.client.post(reverse("timetable:substitutions"), {"date": self.monday.isoformat(), "slot": other_slot.pk, "substitute": self.t3.pk})
        self.assertEqual(r.status_code, 404)
        for u in (self.t1, self.s1, self.parent, self.reg):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("timetable:substitutions")).status_code, 403, u.username)

    def test_teacher_sees_own_cover(self):
        Substitution.objects.create(slot=self.slot, date=self.monday + timedelta(days=7), substitute=self.t3, created_by=self.prin)
        self.client.force_login(self.t3)
        self.assertContains(self.client.get(reverse("timetable:mine")), "Cover duties")
        self.assertEqual(services.teacher_cover(self.t3, self.monday, self.monday + timedelta(days=14)).count(), 1)


class CalendarTests(Base):
    def test_everyone_can_view_scoped(self):
        CalendarEvent.objects.create(title="AlphaOnly", start_date=timezone.localdate(), end_date=timezone.localdate(), campus=self.c1)
        CalendarEvent.objects.create(title="BetaOnly", start_date=timezone.localdate(), end_date=timezone.localdate(), campus=self.c2)
        CalendarEvent.objects.create(title="Everyone", start_date=timezone.localdate(), end_date=timezone.localdate())
        for u, a, b in ((self.s1, True, False), (self.parent, True, False), (self.s2, False, True), (self.t1, True, False), (self.prin, True, False), (self.head, True, True)):
            self.client.force_login(u)
            r = self.client.get(reverse("timetable:calendar"))
            self.assertContains(r, "Everyone")
            self.assertEqual("AlphaOnly" in r.content.decode(), a, u.username)
            self.assertEqual("BetaOnly" in r.content.decode(), b, u.username)

    def test_manage_permissions_and_scope(self):
        url = reverse("timetable:calendar")
        d = timezone.localdate().isoformat()
        for u in (self.s1, self.parent, self.t1, self.reg):
            self.client.force_login(u)
            self.assertEqual(self.client.post(url, {"action": "add_event", "title": "x", "start_date": d}).status_code, 403, u.username)
        self.client.force_login(self.prin)
        self.client.post(url, {"action": "add_event", "title": "Whole school", "start_date": d, "campus": ""})  # principal may not post all-campus
        self.client.post(url, {"action": "add_event", "title": "Other campus", "start_date": d, "campus": self.c2.pk})
        self.assertEqual(CalendarEvent.objects.count(), 0)
        self.client.post(url, {"action": "add_event", "title": "Own", "start_date": d, "campus": self.c1.pk, "kind": "holiday"})
        ev = CalendarEvent.objects.get()
        self.assertEqual((ev.end_date, ev.kind), (date.fromisoformat(d), "holiday"))
        self.client.force_login(self.head)
        self.client.post(url, {"action": "add_event", "title": "All", "start_date": d, "end_date": (timezone.localdate() - timedelta(days=1)).isoformat()})
        self.assertEqual(CalendarEvent.objects.count(), 1)  # end before start rejected
        self.client.post(url, {"action": "add_term", "title": "T1", "start_date": d, "end_date": d})
        self.assertEqual(Term.objects.count(), 1)
        self.client.force_login(self.prin)
        self.client.post(url, {"action": "delete_event", "id": ev.pk})
        self.assertEqual(CalendarEvent.objects.count(), 0)

    def test_principal_cannot_delete_other_campus_item(self):
        ev = CalendarEvent.objects.create(title="Beta", start_date=timezone.localdate(), end_date=timezone.localdate(), campus=self.c2)
        self.client.force_login(self.prin)
        self.assertEqual(self.client.post(reverse("timetable:calendar"), {"action": "delete_event", "id": ev.pk}).status_code, 403)
        self.assertTrue(CalendarEvent.objects.filter(pk=ev.pk).exists())

    def test_month_param_robust_and_holiday_lookup(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("timetable:calendar") + "?month=junk").status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:calendar") + "?month=2026-13").status_code, 200)
        d = date(2026, 12, 25)
        CalendarEvent.objects.create(kind="holiday", title="Break", start_date=d, end_date=d + timedelta(days=2), campus=self.c1)
        self.assertIsNotNone(services.holiday_on(d + timedelta(days=1), self.c1.pk))
        self.assertIsNone(services.holiday_on(d + timedelta(days=1), self.c2.pk))
        self.assertIsNone(services.holiday_on(d + timedelta(days=3), self.c1.pk))

    def test_attendance_page_warns_on_holiday(self):
        today = timezone.localdate()
        CalendarEvent.objects.create(kind="holiday", title="Founders Day", start_date=today, end_date=today)
        self.client.force_login(self.t1)
        self.assertContains(self.client.get(reverse("attendance:mark", args=[self.cls.pk])), "Founders Day")

    def test_month_grid_contains_multi_day_event(self):
        CalendarEvent.objects.create(title="Long", start_date=date(2026, 3, 30), end_date=date(2026, 4, 2))
        weeks = services.month_weeks(2026, 4, CalendarEvent.objects.all())
        days = [c for w in weeks for c in w if c["events"] and c["in_month"]]
        self.assertEqual(len(days), 2)  # 1 and 2 April only
