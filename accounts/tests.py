from django.test import TestCase
from django.urls import reverse

from core.models import SchoolSettings

from .models import User


class Phase1Tests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@x.com", "pw12345")
        self.teacher = User.objects.create_user("t1", password="pw12345", role="teacher", first_name="T")
        self.student = User.objects.create_user("s1", password="pw12345", role="student", first_name="S")
        self.parent = User.objects.create_user("p1", password="pw12345", role="parent", first_name="P")
        self.parent.children.add(self.student)

    def login(self, name):
        self.client.login(username=name, password="pw12345")

    def test_superuser_gets_super_admin_role(self):
        self.assertEqual(self.admin.role, "super_admin")

    def test_login_page_and_dashboards(self):
        self.assertEqual(self.client.get(reverse("accounts:login")).status_code, 200)
        for name, text in [("admin", "Total users"), ("t1", "My Courses"), ("s1", "AI Tutor"), ("p1", "My children")]:
            self.client.logout()
            self.login(name)
            r = self.client.get(reverse("accounts:dashboard"))
            self.assertEqual(r.status_code, 200, name)
            self.assertContains(r, text)

    def test_anonymous_redirected(self):
        r = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(r.status_code, 302)

    def test_non_admin_blocked_from_admin_pages(self):
        for name in ("t1", "s1", "p1"):
            self.client.logout()
            self.login(name)
            self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)
            self.assertEqual(self.client.get(reverse("core:settings")).status_code, 403)

    def test_admin_creates_parent_with_children(self):
        self.login("admin")
        r = self.client.post(reverse("accounts:user_create"), {
            "first_name": "New", "last_name": "Parent", "username": "np", "email": "", "phone": "",
            "role": "parent", "children": [self.student.pk], "is_active": "on",
            "password1": "secret99", "password2": "secret99",
        })
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        np = User.objects.get(username="np")
        self.assertEqual(list(np.children.all()), [self.student])

    def test_admin_edit_and_toggle(self):
        self.login("admin")
        r = self.client.post(reverse("accounts:user_toggle", args=[self.teacher.pk]))
        self.assertEqual(r.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_active)
        r = self.client.get(reverse("accounts:user_edit", args=[self.student.pk]))
        self.assertEqual(r.status_code, 200)

    def test_school_theme_applies_to_everyone(self):
        self.login("admin")
        r = self.client.post(reverse("core:settings"), {
            "school_name": "Test School", "tagline": "Hi", "theme": "midnight",
            "use_custom_colors": "", "custom_primary": "#2563eb", "custom_accent": "#06b6d4",
            "font_style": "serif", "radius": "round", "sidebar_style": "dark", "allow_user_theme": "on",
        })
        self.assertEqual(r.status_code, 302)
        s = SchoolSettings.load()
        self.assertEqual((s.theme, s.font_style, s.radius), ("midnight", "serif", "round"))
        self.client.logout()
        self.login("s1")
        r = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(r, 'data-theme="midnight"')
        self.assertContains(r, 'data-font="serif"')
        self.assertContains(r, "Test School")

    def test_custom_colors_and_user_override(self):
        s = SchoolSettings.load()
        s.use_custom_colors, s.custom_primary = True, "#ff0000"
        s.save()
        self.login("s1")
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "--primary:#ff0000")
        # student picks personal theme -> custom colours no longer forced on them
        self.client.post(reverse("accounts:profile"), {"first_name": "S", "last_name": "", "email": "", "phone": "", "theme": "emerald"})
        r = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(r, 'data-theme="emerald"')
        self.assertNotContains(r, "--primary:#ff0000")
        # school disables personal themes -> back to school theme
        s.allow_user_theme = False
        s.save()
        self.assertContains(self.client.get(reverse("accounts:dashboard")), f'data-theme="{s.theme}"')

    def test_invalid_hex_rejected(self):
        self.login("admin")
        r = self.client.post(reverse("core:settings"), {
            "school_name": "X", "tagline": "", "theme": "ocean", "custom_primary": "red", "custom_accent": "#06b6d4",
            "font_style": "sans", "radius": "soft", "sidebar_style": "themed",
        })
        self.assertEqual(r.status_code, 200)

    def test_logout_and_profile_password(self):
        self.login("t1")
        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:password")).status_code, 200)
        self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)
