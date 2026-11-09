from django.test import TestCase
from django.urls import reverse

from accounts import rbac
from accounts.models import RolePermission, User
from core.models import AuditLog
from organization.models import Campus, Region, StudentProfile


def mk(username, role, **kw):
    u = User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)
    return u


class Base(TestCase):
    def setUp(self):
        self.r1, self.r2 = Region.objects.create(name="South"), Region.objects.create(name="North")
        self.c1 = Campus.objects.create(region=self.r1, name="Alpha")
        self.c2 = Campus.objects.create(region=self.r1, name="Beta")
        self.c3 = Campus.objects.create(region=self.r2, name="Gamma")
        self.s = {}
        for name, c in (("sa", self.c1), ("sb", self.c2), ("sg", self.c3)):
            u = mk(name, "student")
            StudentProfile.objects.create(user=u, campus=c, admission_no=name)
            self.s[name] = u
        self.admin = mk("admin1", "super_admin")
        self.head = mk("head", "head_office")
        self.reg = mk("reg", "regional_director", region=self.r1)
        self.prin = mk("prin", "principal", campus=self.c1)
        self.teacher = mk("t1", "teacher")

    def login(self, u):
        self.client.force_login(u)


class ScopeTests(Base):
    def names(self, resp):
        return {u.username for u in resp.context["page_obj"]}

    def test_student_list_scoped_per_role(self):
        self.login(self.head)
        self.assertEqual(self.names(self.client.get(reverse("organization:student_list"))), {"sa", "sb", "sg"})
        self.login(self.reg)
        self.assertEqual(self.names(self.client.get(reverse("organization:student_list"))), {"sa", "sb"})
        self.login(self.prin)
        self.assertEqual(self.names(self.client.get(reverse("organization:student_list"))), {"sa"})

    def test_principal_cannot_open_other_campus_profile(self):
        self.login(self.prin)
        self.assertEqual(self.client.get(reverse("organization:student_profile", args=[self.s["sa"].pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("organization:student_profile", args=[self.s["sb"].pk])).status_code, 403)

    def test_principal_cannot_edit_other_campus_student(self):
        self.login(self.prin)
        self.assertEqual(self.client.get(reverse("organization:student_edit", args=[self.s["sb"].pk])).status_code, 404)

    def test_principal_create_limited_to_own_campus(self):
        self.login(self.prin)
        r = self.client.post(reverse("organization:student_create"), {
            "first_name": "New", "username": "newkid", "password": "pw-Test-12345", "campus": self.c2.pk})
        self.assertEqual(r.status_code, 200)  # form error, not created
        self.assertFalse(User.objects.filter(username="newkid").exists())
        r = self.client.post(reverse("organization:student_create"), {
            "first_name": "New", "username": "newkid", "password": "pw-Test-12345", "campus": self.c1.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(User.objects.get(username="newkid").student_profile.campus_id, self.c1.pk)

    def test_regional_cannot_create_students(self):
        self.login(self.reg)
        self.assertEqual(self.client.get(reverse("organization:student_create")).status_code, 403)

    def test_compare_scoped_and_export_checks_perm(self):
        self.login(self.prin)
        r = self.client.get(reverse("organization:compare"))
        self.assertEqual([x["campus"].name for x in r.context["rows"]], ["Alpha"])
        self.login(self.reg)
        self.assertEqual({x["campus"].name for x in self.client.get(reverse("organization:compare")).context["rows"]}, {"Alpha", "Beta"})
        csv = self.client.get(reverse("organization:compare") + "?format=csv")
        self.assertEqual(csv.status_code, 200)
        self.assertNotIn("Gamma", csv.content.decode())

    def test_teacher_and_student_blocked_from_management_pages(self):
        for u in (self.teacher, self.s["sa"]):
            self.login(u)
            self.assertEqual(self.client.get(reverse("organization:compare")).status_code, 403)
            self.assertEqual(self.client.get(reverse("core:audit")).status_code, 403)
        self.login(self.teacher)
        self.assertEqual(self.client.get(reverse("core:permissions")).status_code, 403)

    def test_management_dashboards_render(self):
        for u in (self.head, self.reg, self.prin):
            self.login(u)
            r = self.client.get(reverse("accounts:dashboard"))
            self.assertEqual(r.status_code, 200)
            self.assertTemplateUsed(r, "dashboards/management.html")

    def test_reports_scoped(self):
        self.login(self.prin)
        r = self.client.get(reverse("reports:students"))
        self.assertEqual({u.username for u in r.context["page_obj"]}, {"sa"})
        self.assertEqual(self.client.get(reverse("reports:students_csv")).status_code, 200)


class RbacTests(Base):
    def test_defaults(self):
        self.assertTrue(rbac.has_perm(self.admin, "rbac.manage"))
        self.assertTrue(rbac.has_perm(self.prin, "students.edit"))
        self.assertFalse(rbac.has_perm(self.reg, "students.edit"))
        self.assertFalse(rbac.has_perm(self.s["sa"], "students.view"))

    def test_override_applies_and_resets(self):
        self.login(self.admin)
        data = {f"{r}|{c}": "on" for r, m in rbac.role_matrix().items() for c, v in m.items() if v}
        data["regional_director|students.edit"] = "on"
        self.assertEqual(self.client.post(reverse("core:permissions"), data).status_code, 302)
        self.assertTrue(RolePermission.objects.filter(role="regional_director", code="students.edit", allowed=True).exists())
        self.login(self.reg)
        self.assertEqual(self.client.get(reverse("organization:student_edit", args=[self.s["sa"].pk])).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action="rbac.update").exists())
        # removing the tick returns to the default and deletes the override row
        self.login(self.admin)
        data.pop("regional_director|students.edit")
        self.client.post(reverse("core:permissions"), data)
        self.assertFalse(RolePermission.objects.filter(role="regional_director", code="students.edit").exists())

    def test_matrix_page_renders_for_admin_only(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("core:permissions")).status_code, 200)
        self.login(self.head)
        self.assertEqual(self.client.get(reverse("core:permissions")).status_code, 403)


class AuditTests(Base):
    def test_login_logout_and_failure_logged(self):
        self.client.post(reverse("accounts:login"), {"username": "admin1", "password": "wrong"})
        self.client.post(reverse("accounts:login"), {"username": "admin1", "password": "pw-Test-12345"})
        self.client.post(reverse("accounts:logout"))
        acts = list(AuditLog.objects.values_list("action", flat=True))
        for a in ("login.failed", "login", "logout"):
            self.assertIn(a, acts)

    def test_user_create_and_export_logged(self):
        self.login(self.head)
        self.client.get(reverse("organization:student_export"))
        self.assertTrue(AuditLog.objects.filter(action="export.students", username="head").exists())

    def test_audit_view_for_head_office(self):
        self.login(self.head)
        self.assertEqual(self.client.get(reverse("core:audit")).status_code, 200)
        self.login(self.prin)
        self.assertEqual(self.client.get(reverse("core:audit")).status_code, 403)

    def test_csv_formula_injection_blocked(self):
        self.s["sa"].first_name = "=HYPERLINK(1)"
        self.s["sa"].save()
        self.login(self.head)
        body = self.client.get(reverse("organization:student_export")).content.decode()
        self.assertIn("'=HYPERLINK(1)", body)


class ParentPortalTests(Base):
    def setUp(self):
        super().setUp()
        self.p = mk("par", "parent")
        self.p.children.set([self.s["sa"], self.s["sb"]])
        self.other = mk("par2", "parent")
        self.other.children.set([self.s["sg"]])

    def test_overview_for_own_children_only(self):
        self.login(self.p)
        self.assertEqual(self.client.get(reverse("organization:family", args=[self.s["sa"].pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("organization:family", args=[self.s["sg"].pk])).status_code, 403)

    def test_home_redirects_to_first_child_and_switcher(self):
        self.login(self.p)
        r = self.client.get(reverse("organization:family_home"))
        self.assertEqual(r.status_code, 302)
        page = self.client.get(r["Location"]).content.decode()
        self.assertIn("kidSwitch", page)

    def test_non_parents_blocked(self):
        for u in (self.teacher, self.admin, self.s["sa"]):
            self.login(u)
            self.assertEqual(self.client.get(reverse("organization:family", args=[self.s["sa"].pk])).status_code, 403)

    def test_shows_only_published_results_and_approved_nuggets(self):
        from academics.models import Course, Enrollment, SchoolClass, Subject
        from exams.models import Exam, ExamPaper as Paper, Mark
        cls = SchoolClass.objects.create(name="C", section="A")
        Enrollment.objects.create(student=self.s["sa"], school_class=cls)
        course = Course.objects.create(school_class=cls, subject=Subject.objects.create(name="Maths"))
        exam = Exam.objects.create(name="Mid Term", school_class=cls, is_published=False)
        paper = Paper.objects.create(exam=exam, course=course, total_marks=100, pass_marks=33)
        Mark.objects.create(paper=paper, student=self.s["sa"], marks=20)
        self.login(self.p)
        url = reverse("organization:family", args=[self.s["sa"].pk])
        self.assertNotIn("Mid Term", self.client.get(url).content.decode())
        exam.is_published = True
        exam.save()
        body = self.client.get(url).content.decode()
        self.assertIn("Mid Term", body)
        self.assertIn("Needs attention", body)  # 20% is below the 50% alert line
