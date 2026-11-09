from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Course, Enrollment, SchoolClass, Subject
from accounts.models import User
from accounts.rbac import has_perm
from core.models import AuditLog, Notification
from organization.models import Campus, Region, StudentProfile
from risk import services as risk
from risk.models import Alert, EarlyWarningSettings, Intervention

from . import services
from .models import AttendanceRecord, LeaveRequest, StaffAttendance

TODAY = timezone.localdate()


def mk(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


class Base(TestCase):
    def setUp(self):
        reg = Region.objects.create(name="South")
        self.c1, self.c2 = Campus.objects.create(region=reg, name="Alpha"), Campus.objects.create(region=reg, name="Beta")
        self.cls = SchoolClass.objects.create(name="Class 8", section="A", campus=self.c1)
        self.cls2 = SchoolClass.objects.create(name="Class 8", section="B", campus=self.c2)
        sub = Subject.objects.create(name="Maths")
        self.teacher, self.teacher2 = mk("t1", "teacher"), mk("t2", "teacher")
        Course.objects.create(school_class=self.cls, subject=sub, teacher=self.teacher)
        Course.objects.create(school_class=self.cls2, subject=sub, teacher=self.teacher2)
        self.s1, self.s2 = mk("s1", "student"), mk("s2", "student")
        for s, cl, c in ((self.s1, self.cls, self.c1), (self.s2, self.cls2, self.c2)):
            Enrollment.objects.create(student=s, school_class=cl)
            StudentProfile.objects.create(user=s, campus=c, admission_no=s.username)
        self.parent, self.other_parent = mk("par", "parent"), mk("par2", "parent")
        self.parent.children.set([self.s1])
        self.other_parent.children.set([self.s2])
        self.admin, self.head = mk("adm", "super_admin"), mk("head", "head_office")
        self.prin, self.reg = mk("prin", "principal", campus=self.c1), mk("regd", "regional_director", region=reg)

    def mark(self, student, cls, offset, status):
        return AttendanceRecord.objects.create(student=student, school_class=cls, date=TODAY - timedelta(days=offset), status=status)


class MarkingTests(Base):
    def test_teacher_marks_own_class_and_family_notified_once(self):
        self.client.force_login(self.teacher)
        url = reverse("attendance:mark", args=[self.cls.pk])
        r = self.client.post(url, {f"s{self.s1.pk}": "absent", f"n{self.s1.pk}": "fever"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AttendanceRecord.objects.get(student=self.s1, date=TODAY).status, "absent")
        n = Notification.objects.filter(user=self.parent, kind="attendance").count()
        self.assertEqual(n, 1)
        self.client.post(url, {f"s{self.s1.pk}": "absent"})  # re-save: no duplicate notification, no duplicate row
        self.assertEqual(Notification.objects.filter(user=self.parent, kind="attendance").count(), 1)
        self.assertEqual(AttendanceRecord.objects.filter(student=self.s1).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="attendance.mark").exists())

    def test_teacher_cannot_mark_other_class(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("attendance:mark", args=[self.cls2.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("attendance:mark", args=[self.cls2.pk]), {}).status_code, 403)

    def test_student_parent_regional_cannot_mark(self):
        for u in (self.s1, self.parent, self.reg):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("attendance:mark", args=[self.cls.pk])).status_code, 403, u.username)

    def test_principal_marks_own_campus_only(self):
        self.client.force_login(self.prin)
        self.assertEqual(self.client.get(reverse("attendance:mark", args=[self.cls.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("attendance:mark", args=[self.cls2.pk])).status_code, 403)

    def test_future_date_is_clamped_to_today(self):
        self.client.force_login(self.teacher)
        far = (TODAY + timedelta(days=5)).isoformat()
        self.client.post(reverse("attendance:mark", args=[self.cls.pk]), {"date": far, f"s{self.s1.pk}": "present"})
        self.assertFalse(AttendanceRecord.objects.filter(date__gt=TODAY).exists())

    def test_invalid_status_ignored_and_note_truncated(self):
        services.save_sheet(self.cls, TODAY, {self.s1.pk: ("hacked", "x"), 99999: ("present", "")}, self.teacher)
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        services.save_sheet(self.cls, TODAY, {self.s1.pk: ("late", "n" * 500)}, self.teacher)
        self.assertEqual(len(AttendanceRecord.objects.get().note), 160)

    def test_approved_leave_prefills_sheet(self):
        LeaveRequest.objects.create(student=self.s1, from_date=TODAY, to_date=TODAY, reason="x", status="approved")
        rows, saved = services.sheet(self.cls, TODAY)
        self.assertEqual(rows[0]["status"], "leave")
        self.assertFalse(saved)

    def test_summary_counts_are_not_swapped(self):
        for i, st in enumerate(["absent", "absent", "absent", "present", "late"]):
            self.mark(self.s1, self.cls, i, st)
        s = services.summary(self.s1)
        self.assertEqual((s["present"], s["late"], s["absent"]), (1, 1, 3))
        self.assertEqual(s["pct"], 40.0)  # (1+1)/5

    def test_percentage_excludes_leave(self):
        for i, st in enumerate(["present", "present", "late", "absent", "leave", "leave"]):
            self.mark(self.s1, self.cls, i, st)
        s = services.summary(self.s1)
        self.assertEqual(s["pct"], 75.0)  # (2+1)/4
        self.assertEqual(s["leave"], 2)
        self.assertIsNone(services.summary(self.s2)["pct"])


class ViewScopeTests(Base):
    def test_student_and_parent_views(self):
        self.client.force_login(self.s1)
        self.assertEqual(self.client.get(reverse("attendance:my")).status_code, 302)
        self.assertEqual(self.client.get(reverse("attendance:student", args=[self.s1.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("attendance:student", args=[self.s2.pk])).status_code, 403)
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(reverse("attendance:student", args=[self.s1.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("attendance:student", args=[self.s2.pk])).status_code, 403)

    def test_management_scope(self):
        self.client.force_login(self.prin)
        self.assertEqual(self.client.get(reverse("attendance:student", args=[self.s1.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("attendance:student", args=[self.s2.pk])).status_code, 403)
        self.client.force_login(self.teacher2)
        self.assertEqual(self.client.get(reverse("attendance:student", args=[self.s1.pk])).status_code, 403)

    def test_report_scoped_and_csv_safe(self):
        for i in range(5):
            self.mark(self.s1, self.cls, i, "absent")
            self.mark(self.s2, self.cls2, i, "absent")
        self.s1.first_name = "=HYPERLINK(1)"
        self.s1.save()
        self.client.force_login(self.prin)
        r = self.client.get(reverse("attendance:report") + "?format=csv")
        body = r.content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", body)
        self.assertNotIn("s2", body)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("attendance:report")).status_code, 403)
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("attendance:report")).status_code, 200)

    def test_profile_cards_render(self):
        self.mark(self.s1, self.cls, 1, "present")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("organization:student_profile", args=[self.s1.pk])), "Attendance (30 days)")
        self.client.force_login(self.parent)
        self.assertContains(self.client.get(reverse("organization:family", args=[self.s1.pk])), "Attendance (30 days)")

    def test_staff_attendance(self):
        User.objects.filter(pk=self.teacher.pk).update(campus=self.c1)
        User.objects.filter(pk=self.teacher2.pk).update(campus=self.c2)
        self.client.force_login(self.prin)
        self.assertEqual(self.client.get(reverse("attendance:staff")).status_code, 200)
        self.client.post(reverse("attendance:staff"), {f"t{self.teacher.pk}": "absent", f"t{self.teacher2.pk}": "absent"})
        self.assertTrue(StaffAttendance.objects.filter(teacher=self.teacher, status="absent").exists())
        self.assertFalse(StaffAttendance.objects.filter(teacher=self.teacher2).exists())  # other campus: not in scope
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("attendance:staff")).status_code, 403)


class LeaveTests(Base):
    def test_parent_requests_teacher_approves(self):
        self.client.force_login(self.parent)
        d = TODAY.isoformat()
        r = self.client.post(reverse("attendance:leave_request", args=[self.s1.pk]), {"from_date": d, "to_date": d, "reason": "Wedding"})
        self.assertEqual(r.status_code, 302)
        lr = LeaveRequest.objects.get()
        self.assertTrue(Notification.objects.filter(user=self.teacher, kind="attendance").exists())
        self.client.force_login(self.teacher2)  # not this student's teacher
        self.assertEqual(self.client.post(reverse("attendance:leave_decide", args=[lr.pk]), {"decision": "approved"}).status_code, 404)
        self.client.force_login(self.parent)
        self.assertEqual(self.client.post(reverse("attendance:leave_decide", args=[lr.pk]), {"decision": "approved"}).status_code, 404)
        self.client.force_login(self.teacher)
        self.client.post(reverse("attendance:leave_decide", args=[lr.pk]), {"decision": "approved"})
        lr.refresh_from_db()
        self.assertEqual(lr.status, "approved")
        self.assertEqual(lr.decided_by, self.teacher)
        self.assertTrue(Notification.objects.filter(user=self.parent, title__contains="Leave approved").exists())
        # decided already: cannot be changed again
        self.assertEqual(self.client.post(reverse("attendance:leave_decide", args=[lr.pk]), {"decision": "rejected"}).status_code, 404)

    def test_validation_and_ownership(self):
        self.client.force_login(self.parent)
        d = TODAY.isoformat()
        bad = (TODAY - timedelta(days=2)).isoformat()
        self.client.post(reverse("attendance:leave_request", args=[self.s1.pk]), {"from_date": d, "to_date": bad, "reason": "x"})
        self.client.post(reverse("attendance:leave_request", args=[self.s1.pk]), {"from_date": d, "to_date": d, "reason": ""})
        self.client.post(reverse("attendance:leave_request", args=[self.s1.pk]), {"from_date": "junk", "to_date": d, "reason": "x"})
        self.assertEqual(LeaveRequest.objects.count(), 0)
        self.assertEqual(self.client.post(reverse("attendance:leave_request", args=[self.s2.pk]), {"from_date": d, "to_date": d, "reason": "x"}).status_code, 403)

    def test_decide_requires_post_and_valid_decision(self):
        lr = LeaveRequest.objects.create(student=self.s1, from_date=TODAY, to_date=TODAY, reason="x")
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("attendance:leave_decide", args=[lr.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse("attendance:leave_decide", args=[lr.pk]), {"decision": "weird"}).status_code, 403)

    def test_leave_list_scope(self):
        LeaveRequest.objects.create(student=self.s1, from_date=TODAY, to_date=TODAY, reason="mine")
        LeaveRequest.objects.create(student=self.s2, from_date=TODAY, to_date=TODAY, reason="theirs")
        self.client.force_login(self.teacher)
        r = self.client.get(reverse("attendance:leaves"))
        self.assertContains(r, "mine")
        self.assertNotContains(r, "theirs")
        self.client.force_login(self.s1)
        self.assertEqual(self.client.get(reverse("attendance:leaves")).status_code, 403)


class RiskTests(Base):
    def low_att(self, student, cls):
        for i in range(10):
            self.mark(student, cls, i, "absent" if i < 6 else "present")

    def test_scan_creates_updates_resolves_idempotently(self):
        self.low_att(self.s1, self.cls)
        r = risk.scan()
        self.assertEqual((r["created"], r["flagged"]), (1, 1))
        a = Alert.objects.get()
        self.assertEqual((a.student, a.level, a.status), (self.s1, "watch", "open"))
        r2 = risk.scan()
        self.assertEqual((r2["created"], r2["updated"]), (0, 0))
        self.assertEqual(Alert.objects.count(), 1)
        AttendanceRecord.objects.filter(student=self.s1).update(status="present")
        r3 = risk.scan()
        self.assertEqual(r3["resolved"], 1)
        a.refresh_from_db()
        self.assertEqual(a.status, "resolved")

    def test_in_progress_alert_never_auto_resolved(self):
        self.low_att(self.s1, self.cls)
        risk.scan()
        Alert.objects.update(status="in_progress")
        AttendanceRecord.objects.filter(student=self.s1).update(status="present")
        risk.scan()
        self.assertEqual(Alert.objects.get().status, "in_progress")

    def test_thresholds_are_school_controlled(self):
        for i in range(10):
            self.mark(self.s1, self.cls, i, "absent" if i < 2 else "present")  # 80%
        self.assertEqual(risk.scan()["flagged"], 0)
        cfg = EarlyWarningSettings.get()
        cfg.attendance_below = 90
        cfg.save()
        self.assertEqual(risk.scan()["flagged"], 1)
        cfg.min_signals = 2
        cfg.save()
        risk.scan()
        self.assertEqual(Alert.objects.get().status, "resolved")

    def test_too_few_marked_days_is_not_a_signal(self):
        self.mark(self.s1, self.cls, 1, "absent")
        self.assertEqual(risk.scan()["flagged"], 0)

    def test_visibility_scope(self):
        self.low_att(self.s1, self.cls)
        self.low_att(self.s2, self.cls2)
        risk.scan()
        a1, a2 = Alert.objects.get(student=self.s1), Alert.objects.get(student=self.s2)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("risk:detail", args=[a1.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("risk:detail", args=[a2.pk])).status_code, 404)
        self.client.force_login(self.prin)
        self.assertEqual(self.client.get(reverse("risk:detail", args=[a2.pk])).status_code, 404)
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("risk:detail", args=[a2.pk])).status_code, 200)
        for u in (self.s1, self.parent):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("risk:index")).status_code, 403, u.username)
            self.assertEqual(self.client.get(reverse("risk:detail", args=[a1.pk])).status_code, 403)

    def test_workflow_task_notify_resolve(self):
        self.low_att(self.s1, self.cls)
        risk.scan()
        a = Alert.objects.get()
        url = reverse("risk:detail", args=[a.pk])
        self.client.force_login(self.teacher)
        self.client.post(url, {"action": "task", "title": "Call parents", "assigned_to": self.prin.pk})
        a.refresh_from_db()
        self.assertEqual(a.status, "in_progress")
        t = Intervention.objects.get(title="Call parents")
        self.assertTrue(Notification.objects.filter(user=self.prin, kind="risk").exists())
        self.client.post(url, {"action": "task_done", "task": t.pk, "outcome": "Spoke to mother"})
        t.refresh_from_db()
        self.assertEqual((t.status, t.outcome_note), ("done", "Spoke to mother"))
        self.client.post(url, {"action": "notify", "message": "Please call school"})
        self.assertTrue(Notification.objects.filter(user=self.parent, kind="risk").exists())
        self.assertFalse(Notification.objects.filter(user=self.other_parent, kind="risk").exists())
        self.client.post(url, {"action": "resolve", "note": ""})
        a.refresh_from_db()
        self.assertNotEqual(a.status, "resolved")  # note is required
        self.client.post(url, {"action": "resolve", "note": "Attendance improved after meeting"})
        a.refresh_from_db()
        self.assertEqual((a.status, a.resolved_by), ("resolved", self.teacher))
        self.client.post(url, {"action": "task", "title": "Late task"})
        self.assertFalse(Intervention.objects.filter(title="Late task").exists())  # resolved alerts are frozen

    def test_new_alert_after_resolve(self):
        self.low_att(self.s1, self.cls)
        risk.scan()
        Alert.objects.update(status="resolved")
        risk.scan()
        self.assertEqual(Alert.objects.count(), 2)
        self.assertEqual(Alert.objects.exclude(status="resolved").count(), 1)

    def test_settings_and_scan_permissions(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("risk:settings")).status_code, 403)
        self.assertEqual(self.client.post(reverse("risk:scan")).status_code, 403)
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("risk:scan")).status_code, 405)
        r = self.client.post(reverse("risk:settings"), {"window_days": 30, "attendance_below": 150, "exam_below": 50, "exam_drop": 10,
                                                       "quiz_below": 50, "struggling_nuggets": 2, "min_signals": 1})
        self.assertEqual(r.status_code, 200)  # invalid → form redisplayed
        r = self.client.post(reverse("risk:settings"), {"window_days": 30, "attendance_below": 70, "exam_below": 50, "exam_drop": 10,
                                                       "quiz_below": 50, "struggling_nuggets": 2, "min_signals": 1})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(EarlyWarningSettings.get().attendance_below, 70)
        self.client.post(reverse("risk:scan"))
        self.assertTrue(AuditLog.objects.filter(action="risk.scan").exists())

    def test_level_by_signal_count(self):
        self.assertEqual([risk.level_for(n) for n in (1, 2, 3, 5)], ["watch", "medium", "high", "high"])

    def test_scan_command(self):
        from django.core.management import call_command
        self.low_att(self.s1, self.cls)
        call_command("scan_risk", verbosity=0)
        self.assertEqual(Alert.objects.count(), 1)

    def test_permissions_registered(self):
        self.assertTrue(has_perm(self.teacher, "attendance.mark"))
        self.assertFalse(has_perm(self.reg, "attendance.mark"))
        self.assertFalse(has_perm(self.teacher, "risk.configure"))
        self.assertFalse(has_perm(self.parent, "risk.view"))
