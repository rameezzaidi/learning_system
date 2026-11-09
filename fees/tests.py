from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from academics.models import Enrollment, SchoolClass
from accounts.models import User
from core.models import AuditLog, Notification
from organization.models import Campus, Region, StudentProfile

from . import services
from .models import FeeDefault, LedgerEntry, StudentFeePlan

D = Decimal


def mk(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


class Base(TestCase):
    def setUp(self):
        reg = Region.objects.create(name="South")
        self.c1, self.c2 = Campus.objects.create(region=reg, name="Alpha"), Campus.objects.create(region=reg, name="Beta")
        self.cls = SchoolClass.objects.create(name="Class 8", section="A", campus=self.c1)
        self.cls2 = SchoolClass.objects.create(name="Class 8", section="B", campus=self.c2)
        FeeDefault.objects.create(school_class=self.cls, monthly_amount=D("5000"))
        FeeDefault.objects.create(school_class=self.cls2, monthly_amount=D("4000"))
        self.s1, self.s2 = mk("s1", "student"), mk("s2", "student")
        for s, cl, c in ((self.s1, self.cls, self.c1), (self.s2, self.cls2, self.c2)):
            Enrollment.objects.create(student=s, school_class=cl)
            StudentProfile.objects.create(user=s, campus=c, admission_no=s.username)
        self.parent, self.other_parent = mk("par", "parent"), mk("par2", "parent")
        self.parent.children.set([self.s1])
        self.other_parent.children.set([self.s2])
        self.admin, self.head = mk("adm", "super_admin"), mk("head", "head_office")
        self.prin, self.reg = mk("prin", "principal", campus=self.c1), mk("regd", "regional_director", region=reg)
        self.teacher = mk("t1", "teacher")

    def login(self, u):
        self.client.force_login(u)


class GenerationTests(Base):
    def test_generate_bills_each_student_once_and_is_idempotent(self):
        r = services.generate(date(2026, 11, 15), notify=False)
        self.assertEqual(r["entries"], 2)
        self.assertEqual(services.balance(self.s1), D("5000"))
        self.assertEqual(services.balance(self.s2), D("4000"))
        self.assertEqual(services.generate(date(2026, 11, 30), notify=False)["entries"], 0)
        self.assertEqual(LedgerEntry.objects.filter(kind="monthly").count(), 2)

    def test_catch_up_from_plan_start_month(self):
        StudentFeePlan.objects.create(student=self.s1, start_month=date(2026, 9, 20))
        services.generate(date(2026, 11, 1), notify=False)
        months = list(LedgerEntry.objects.filter(student=self.s1).values_list("month", flat=True))
        self.assertEqual(months, [date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)])
        self.assertEqual(services.balance(self.s1), D("15000"))

    def test_plan_amount_discount_and_inactive(self):
        StudentFeePlan.objects.create(student=self.s1, start_month=date(2026, 11, 1), monthly_amount=D("6000"), discount=D("1500"))
        StudentFeePlan.objects.create(student=self.s2, start_month=date(2026, 11, 1), is_active=False)
        services.generate(date(2026, 11, 1), notify=False)
        self.assertEqual(services.balance(self.s1), D("4500"))
        self.assertEqual(services.balance(self.s2), D("0"))

    def test_class_default_change_does_not_alter_past_charges(self):
        services.generate(date(2026, 11, 1), notify=False)
        FeeDefault.objects.filter(school_class=self.cls).update(monthly_amount=D("9000"))
        services.generate(date(2026, 12, 1), notify=False)
        self.assertEqual(list(LedgerEntry.objects.filter(student=self.s1).values_list("debit", flat=True)), [D("5000"), D("9000")])

    def test_no_fee_means_skipped(self):
        FeeDefault.objects.all().delete()
        r = services.generate(date(2026, 11, 1), notify=False)
        self.assertEqual((r["entries"], r["skipped"]), (0, 2))

    def test_duplicate_monthly_row_blocked_by_database(self):
        services.generate(date(2026, 11, 1), notify=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerEntry.objects.create(student=self.s1, kind="monthly", month=date(2026, 11, 1), entry_date=date(2026, 11, 1), debit=D("1"))

    def test_voided_monthly_can_be_rebilled(self):
        services.generate(date(2026, 11, 1), notify=False)
        e = LedgerEntry.objects.get(student=self.s1)
        services.void(e, "wrong class fee", self.admin)
        self.assertEqual(services.balance(self.s1), D("0"))
        services.generate(date(2026, 11, 1), notify=False)
        self.assertEqual(services.balance(self.s1), D("5000"))

    def test_december_to_january_rollover_and_command(self):
        self.assertEqual(services.next_month(date(2026, 12, 1)), date(2027, 1, 1))
        call_command("generate_fees", "--month", "2026-12", "--no-notify")
        self.assertEqual(LedgerEntry.objects.filter(month=date(2026, 12, 1)).count(), 2)

    def test_notifies_family_on_billing(self):
        services.generate(date(2026, 11, 1))
        self.assertTrue(Notification.objects.filter(user=self.s1, kind="fees").exists())
        self.assertTrue(Notification.objects.filter(user=self.parent, kind="fees").exists())
        self.assertFalse(Notification.objects.filter(user=self.other_parent, kind="fees", body__contains="5000").exists())


class LedgerTests(Base):
    def test_payment_receipt_running_balance_and_advance(self):
        services.generate(date(2026, 11, 1), notify=False)
        e = services.record_payment(self.s1, D("3000"), "cash", by=self.admin)
        self.assertEqual(e.receipt_no, f"R-{e.pk:06d}")
        self.assertEqual(services.balance(self.s1), D("2000"))
        services.record_payment(self.s1, D("3000"), "bank", by=self.admin)
        self.assertEqual(services.balance(self.s1), D("-1000"))  # advance
        rows = services.ledger_rows(self.s1)
        self.assertEqual([r["balance"] for r in rows], [D("5000"), D("2000"), D("-1000")])

    def test_void_excluded_from_balance_but_kept(self):
        e = services.record_payment(self.s1, D("100"), "cash", by=self.admin)
        services.void(e, "typo", self.admin)
        self.assertEqual(services.balance(self.s1), D("0"))
        self.assertEqual(LedgerEntry.objects.filter(student=self.s1).count(), 1)

    def test_negative_amount_rejected_by_db(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerEntry.objects.create(student=self.s1, kind="charge", entry_date=date(2026, 1, 1), debit=D("-5"))


class AccessTests(Base):
    def setUp(self):
        super().setUp()
        services.generate(date(2026, 11, 1), notify=False)

    def test_who_can_see_ledger(self):
        url = reverse("fees:ledger", args=[self.s1.pk])
        for u, code in ((self.admin, 200), (self.head, 200), (self.prin, 200), (self.reg, 200), (self.s1, 200), (self.parent, 200),
                        (self.s2, 403), (self.other_parent, 403), (self.teacher, 403), (mk("prin2", "principal", campus=self.c2), 403)):
            self.login(u)
            self.assertEqual(self.client.get(url).status_code, code, u.username)

    def test_collect_and_manage_permissions(self):
        pay = reverse("fees:pay", args=[self.s1.pk])
        data = {"amount": "1000", "method": "cash"}
        self.login(self.parent)
        self.assertEqual(self.client.post(pay, data).status_code, 403)
        self.login(self.reg)
        self.assertEqual(self.client.post(pay, data).status_code, 403)
        self.login(self.head)  # head office may manage but not collect by default
        self.assertEqual(self.client.post(pay, data).status_code, 403)
        self.login(self.prin)
        self.assertEqual(self.client.post(pay, data).status_code, 302)
        self.assertEqual(services.balance(self.s1), D("4000"))
        self.assertTrue(AuditLog.objects.filter(action="fees.payment", username="prin").exists())
        self.assertEqual(self.client.post(reverse("fees:entry", args=[self.s1.pk]), {"kind": "charge", "amount": "10", "description": "x"}).status_code, 403)
        self.login(self.head)
        self.client.post(reverse("fees:entry", args=[self.s1.pk]), {"kind": "discount", "amount": "500", "description": "Sibling"})
        self.assertEqual(services.balance(self.s1), D("3500"))

    def test_principal_cannot_touch_other_campus(self):
        self.login(self.prin)
        self.assertEqual(self.client.post(reverse("fees:pay", args=[self.s2.pk]), {"amount": "1", "method": "cash"}).status_code, 403)

    def test_invalid_payment_not_saved(self):
        self.login(self.prin)
        self.client.post(reverse("fees:pay", args=[self.s1.pk]), {"amount": "-5", "method": "cash"})
        self.client.post(reverse("fees:pay", args=[self.s1.pk]), {"amount": "0", "method": "cash"})
        self.assertEqual(LedgerEntry.objects.filter(kind="payment").count(), 0)

    def test_void_requires_reason_and_manage(self):
        e = LedgerEntry.objects.get(student=self.s1)
        self.login(self.prin)
        self.assertEqual(self.client.post(reverse("fees:void", args=[e.pk]), {"reason": "x"}).status_code, 403)
        self.login(self.head)
        self.client.post(reverse("fees:void", args=[e.pk]), {"reason": ""})
        e.refresh_from_db()
        self.assertFalse(e.is_void)
        self.client.post(reverse("fees:void", args=[e.pk]), {"reason": "Wrong class"})
        e.refresh_from_db()
        self.assertTrue(e.is_void)

    def test_dashboard_scope_totals_and_export(self):
        self.login(self.prin)
        r = self.client.get(reverse("fees:dashboard") + "?month=2026-11")
        self.assertEqual([t[0].username for t in r.context["defaulters"]], ["s1"])
        self.assertEqual(r.context["d"]["outstanding"], D("5000"))
        self.login(self.head)
        r = self.client.get(reverse("fees:dashboard") + "?month=2026-11")
        self.assertEqual((r.context["d"]["billed"], r.context["d"]["outstanding"]), (D("9000"), D("9000")))
        self.assertEqual(self.client.get(reverse("fees:dashboard") + "?format=csv").status_code, 200)
        for u in (self.teacher, self.s1, self.parent):
            self.login(u)
            self.assertEqual(self.client.get(reverse("fees:dashboard")).status_code, 403)

    def test_generate_button_requires_manage_and_is_scoped(self):
        self.login(self.prin)
        self.assertEqual(self.client.post(reverse("fees:generate"), {"month": "2026-12"}).status_code, 403)
        self.login(self.head)
        self.client.post(reverse("fees:generate"), {"month": "2026-12"})
        self.assertEqual(LedgerEntry.objects.filter(month=date(2026, 12, 1)).count(), 2)

    def test_class_fee_save(self):
        self.login(self.head)
        self.client.post(reverse("fees:defaults"), {f"c{self.cls.pk}": "7500", f"c{self.cls2.pk}": ""})
        self.assertEqual(FeeDefault.objects.get(school_class=self.cls).monthly_amount, D("7500"))
        self.assertFalse(FeeDefault.objects.filter(school_class=self.cls2).exists())

    def test_plan_form_saves_month_input(self):
        self.login(self.head)
        r = self.client.post(reverse("fees:plan", args=[self.s1.pk]), {"monthly_amount": "", "discount": "200", "start_month": "2026-08", "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StudentFeePlan.objects.get(student=self.s1).start_month, date(2026, 8, 1))

    def test_receipt_access(self):
        e = services.record_payment(self.s1, D("100"), "cash", by=self.admin)
        url = reverse("fees:receipt", args=[e.pk])
        self.login(self.parent)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.login(self.other_parent)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_profile_and_family_show_fees_only_to_authorised(self):
        url = reverse("organization:student_profile", args=[self.s1.pk])
        self.login(self.admin)
        self.assertIn("Full ledger", self.client.get(url).content.decode())
        self.login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.parent)
        self.assertIn("Full ledger", self.client.get(reverse("organization:family", args=[self.s1.pk])).content.decode())

    def test_my_redirects(self):
        self.login(self.s1)
        self.assertEqual(self.client.get(reverse("fees:my")).status_code, 302)
        self.login(self.parent)
        self.assertEqual(self.client.get(reverse("fees:my"))["Location"], reverse("fees:ledger", args=[self.s1.pk]))
        self.login(self.teacher)
        self.assertEqual(self.client.get(reverse("fees:my")).status_code, 403)


class AutoGenerateTests(Base):
    def test_dashboard_bills_automatically_once(self):
        from django.core.cache import cache
        from django.test import override_settings
        cache.clear()
        with override_settings(FEES_AUTO_GENERATE=True):
            self.login(self.admin)
            self.client.get(reverse("accounts:dashboard"))
            n = LedgerEntry.objects.filter(kind="monthly").count()
            self.assertEqual(n, 2)
            self.client.get(reverse("accounts:dashboard"))
            self.assertEqual(LedgerEntry.objects.filter(kind="monthly").count(), 2)
        cache.clear()

    def test_disabled_by_default_in_tests(self):
        self.login(self.admin)
        self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(LedgerEntry.objects.count(), 0)
