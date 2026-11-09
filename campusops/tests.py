from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Enrollment, SchoolClass
from accounts.models import User
from organization.models import Campus, Region, StudentProfile

from .models import Book, Loan, Route, RouteStudent


def mk(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


class Base(TestCase):
    def setUp(self):
        reg = Region.objects.create(name="S")
        self.c1, self.c2 = Campus.objects.create(region=reg, name="Alpha"), Campus.objects.create(region=reg, name="Beta")
        self.cls = SchoolClass.objects.create(name="C8", section="A", campus=self.c1)
        self.s1, self.s2 = mk("s1", "student"), mk("s2", "student")
        for s, c in ((self.s1, self.c1), (self.s2, self.c2)):
            Enrollment.objects.create(student=s, school_class=self.cls)
            StudentProfile.objects.create(user=s, campus=c, admission_no="ADM-" + s.username)
        self.parent = mk("par", "parent")
        self.parent.children.set([self.s1])
        self.admin, self.head, self.teacher = mk("adm", "super_admin"), mk("head", "head_office"), mk("t1", "teacher")
        self.prin, self.prin2 = mk("prin", "principal", campus=self.c1), mk("prin2", "principal", campus=self.c2)
        self.reg = mk("regd", "regional_director", region=reg)


class LibraryTests(Base):
    def test_issue_availability_return_and_fine(self):
        b = Book.objects.create(title="Oliver Twist", copies=1)
        self.client.force_login(self.prin)
        url = reverse("campusops:library")
        self.client.post(url, {"action": "issue", "book": b.pk, "borrower": "S1"})
        self.assertEqual(Loan.objects.count(), 1)
        self.assertEqual(b.available, 0)
        self.client.post(url, {"action": "issue", "book": b.pk, "borrower": "s2"})  # no copy left
        self.assertEqual(Loan.objects.count(), 1)
        loan = Loan.objects.get()
        Loan.objects.filter(pk=loan.pk).update(due_on=timezone.localdate() - timedelta(days=3))
        self.client.post(url, {"action": "return", "loan": loan.pk})
        loan.refresh_from_db()
        self.assertEqual((loan.returned_on, loan.fine), (timezone.localdate(), Decimal("15")))
        self.assertEqual(b.available, 1)
        self.client.post(url, {"action": "return", "loan": loan.pk})  # already returned: 404, fine unchanged
        loan.refresh_from_db()
        self.assertEqual(loan.fine, Decimal("15"))

    def test_borrow_limit_unknown_borrower_and_admission_no(self):
        books = [Book.objects.create(title=f"B{i}", copies=1) for i in range(6)]
        self.client.force_login(self.admin)
        url = reverse("campusops:library")
        for b in books:
            self.client.post(url, {"action": "issue", "book": b.pk, "borrower": "ADM-s1"})
        self.assertEqual(Loan.objects.filter(borrower=self.s1).count(), 5)
        self.client.post(url, {"action": "issue", "book": books[0].pk, "borrower": "ghost"})
        self.assertEqual(Loan.objects.count(), 5)

    def test_permissions_and_browse(self):
        Book.objects.create(title="Visible Book", copies=1)
        for u in (self.s1, self.teacher, self.parent):
            self.client.force_login(u)
            self.assertContains(self.client.get(reverse("campusops:library")), "Visible Book")
            self.assertEqual(self.client.post(reverse("campusops:library"), {"action": "add", "title": "x"}).status_code, 403, u.username)
        self.client.force_login(self.reg)  # no library.manage by default
        self.assertEqual(self.client.post(reverse("campusops:library"), {"action": "add", "title": "x"}).status_code, 403)
        self.assertEqual(Book.objects.count(), 1)

    def test_search_and_campus_scope(self):
        Book.objects.create(title="Alpha Only", campus=self.c1)
        Book.objects.create(title="Beta Only", campus=self.c2)
        Book.objects.create(title="Shared", author="Hawking")
        self.client.force_login(self.prin)
        body = self.client.get(reverse("campusops:library")).content.decode()
        self.assertIn("Alpha Only", body)
        self.assertNotIn("Beta Only", body)
        self.assertIn("Shared", self.client.get(reverse("campusops:library") + "?q=hawk").content.decode())


class TransportTests(Base):
    def test_route_assign_capacity_and_scope(self):
        self.client.force_login(self.prin)
        url = reverse("campusops:transport")
        self.client.post(url, {"action": "route", "name": "North", "campus": self.c1.pk, "capacity": "1"})
        self.client.post(url, {"action": "route", "name": "Other campus", "campus": self.c2.pk})
        self.client.post(url, {"action": "route", "name": "No campus"})
        self.assertEqual(Route.objects.count(), 1)
        r = Route.objects.get()
        self.client.post(url, {"action": "assign", "route": r.pk, "student": "s1", "stop": "Market"})
        self.assertEqual(RouteStudent.objects.get().stop, "Market")
        self.client.post(url, {"action": "assign", "route": r.pk, "student": "s2"})  # other campus student: not in scope
        self.assertEqual(RouteStudent.objects.count(), 1)
        self.client.post(url, {"action": "assign", "route": r.pk, "student": "s1", "stop": "School gate"})  # re-assign same student ok even when full
        self.assertEqual(RouteStudent.objects.get().stop, "School gate")

    def test_full_route_blocks_new_rider(self):
        r = Route.objects.create(name="R", campus=self.c1, capacity=1)
        s3 = mk("s3", "student")
        StudentProfile.objects.create(user=s3, campus=self.c1)
        RouteStudent.objects.create(route=r, student=self.s1)
        self.client.force_login(self.prin)
        self.client.post(reverse("campusops:transport"), {"action": "assign", "route": r.pk, "student": "s3"})
        self.assertEqual(RouteStudent.objects.count(), 1)

    def test_visibility(self):
        r = Route.objects.create(name="Alpha route", campus=self.c1, vehicle_no="KHI-1", driver_name="Karim")
        Route.objects.create(name="Beta route", campus=self.c2)
        RouteStudent.objects.create(route=r, student=self.s1, stop="Main")
        self.client.force_login(self.s1)
        body = self.client.get(reverse("campusops:transport")).content.decode()
        self.assertIn("KHI-1", body)
        self.assertNotIn("Beta route", body)
        self.client.force_login(self.parent)
        self.assertContains(self.client.get(reverse("campusops:transport")), "Alpha route")
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("campusops:transport")).status_code, 403)
        self.client.force_login(self.reg)  # view only
        self.assertEqual(self.client.get(reverse("campusops:transport")).status_code, 200)
        self.assertEqual(self.client.post(reverse("campusops:transport"), {"action": "route", "name": "x", "campus": self.c1.pk}).status_code, 403)
        self.client.force_login(self.prin2)
        self.client.post(reverse("campusops:transport"), {"action": "delete_route", "id": r.pk})
        self.assertTrue(Route.objects.filter(pk=r.pk).exists())  # not in prin2's scope
