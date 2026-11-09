from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .models import Course, Enrollment, Lesson, LessonProgress, SchoolClass, Subject, progress_for


class Phase2Tests(TestCase):
    def setUp(self):
        mk = User.objects.create_user
        self.admin = User.objects.create_superuser("admin", "a@x.com", "pw12345")
        self.t1 = mk("t1", password="pw12345", role="teacher")
        self.t2 = mk("t2", password="pw12345", role="teacher")
        self.s1 = mk("s1", password="pw12345", role="student")
        self.s2 = mk("s2", password="pw12345", role="student")
        self.s_out = mk("s3", password="pw12345", role="student")
        self.p1 = mk("p1", password="pw12345", role="parent")
        self.p1.children.add(self.s1)
        self.p2 = mk("p2", password="pw12345", role="parent")
        self.cls = SchoolClass.objects.create(name="Class 8", section="A")
        self.other = SchoolClass.objects.create(name="Class 9", section="B")
        Enrollment.objects.create(student=self.s1, school_class=self.cls)
        Enrollment.objects.create(student=self.s2, school_class=self.cls)
        Enrollment.objects.create(student=self.s_out, school_class=self.other)
        self.math = Subject.objects.create(name="Math")
        self.course = Course.objects.create(school_class=self.cls, subject=self.math, teacher=self.t1)
        self.l1 = Lesson.objects.create(course=self.course, title="L1", content="hello")
        self.l2 = Lesson.objects.create(course=self.course, title="L2", content="world")
        self.draft = Lesson.objects.create(course=self.course, title="Draft", content="x", is_published=False)

    def login(self, u):
        self.client.logout()
        self.client.login(username=u, password="pw12345")

    def test_lesson_auto_position(self):
        self.assertEqual([self.l1.position, self.l2.position, self.draft.position], [1, 2, 3])

    def test_admin_class_subject_course_flow(self):
        self.login("admin")
        r = self.client.post(reverse("academics:class_create"), {"name": "Class 10", "section": "C", "academic_year": ""})
        self.assertEqual(r.status_code, 302)
        c = SchoolClass.objects.get(name="Class 10")
        self.client.post(reverse("academics:subject_list"), {"name": "Physics", "code": "PHY"})
        phys = Subject.objects.get(name="Physics")
        r = self.client.post(reverse("academics:course_create", args=[c.pk]),
                             {"subject": phys.pk, "teacher": self.t2.pk, "description": ""})
        self.assertEqual(r.status_code, 302)
        # duplicate subject in same class is rejected
        r = self.client.post(reverse("academics:course_create", args=[c.pk]),
                             {"subject": phys.pk, "teacher": self.t2.pk, "description": ""})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Course.objects.filter(school_class=c).count(), 1)
        for name in ("class_list", "subject_list"):
            self.assertEqual(self.client.get(reverse(f"academics:{name}")).status_code, 200)
        self.assertEqual(self.client.get(reverse("academics:class_detail", args=[c.pk])).status_code, 200)

    def test_enroll_moves_student(self):
        self.login("admin")
        r = self.client.post(reverse("academics:enroll", args=[self.cls.pk]), {"students": [self.s_out.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Enrollment.objects.get(student=self.s_out).school_class, self.cls)
        self.client.post(reverse("academics:unenroll", args=[self.cls.pk, self.s_out.pk]))
        self.assertFalse(Enrollment.objects.filter(student=self.s_out).exists())

    def test_admin_only_pages_blocked_for_others(self):
        for u in ("t1", "s1", "p1"):
            self.login(u)
            self.assertEqual(self.client.get(reverse("academics:class_list")).status_code, 403)
            self.assertEqual(self.client.get(reverse("academics:subject_list")).status_code, 403)

    def test_teacher_manages_only_own_course(self):
        self.login("t1")
        r = self.client.post(reverse("academics:lesson_create", args=[self.course.pk]),
                             {"title": "New", "kind": "text", "content": "body", "is_published": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Lesson.objects.filter(title="New").exists())
        self.assertEqual(self.client.get(reverse("academics:course_detail", args=[self.course.pk])).status_code, 200)
        self.login("t2")
        self.assertEqual(self.client.get(reverse("academics:course_detail", args=[self.course.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("academics:lesson_create", args=[self.course.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("academics:lesson_delete", args=[self.l1.pk])).status_code, 403)

    def test_lesson_validation_and_file_upload(self):
        self.login("t1")
        r = self.client.post(reverse("academics:lesson_create", args=[self.course.pk]),
                             {"title": "V", "kind": "video", "is_published": "on"})
        self.assertEqual(r.status_code, 200)  # missing url
        import tempfile
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            f = SimpleUploadedFile("sheet.txt", b"data")
            r = self.client.post(reverse("academics:lesson_create", args=[self.course.pk]),
                                 {"title": "F", "kind": "file", "file": f, "is_published": "on"})
            self.assertEqual(r.status_code, 302)
            self.assertTrue(Lesson.objects.get(title="F").file.name.endswith(".txt"))

    def test_student_sees_published_only_and_tracks_progress(self):
        self.login("s1")
        r = self.client.get(reverse("academics:course_detail", args=[self.course.pk]))
        self.assertContains(r, "L1")
        self.assertNotContains(r, "Draft")
        self.assertEqual(self.client.get(reverse("academics:lesson_view", args=[self.draft.pk])).status_code, 403)
        self.assertEqual(progress_for(self.s1, self.course)["done"], 0)
        self.client.get(reverse("academics:lesson_view", args=[self.l1.pk]))  # opening = completing, no button
        self.assertEqual(progress_for(self.s1, self.course), {"done": 1, "total": 2, "pct": 50})
        self.assertNotContains(self.client.get(reverse("academics:lesson_view", args=[self.l1.pk])), "Mark as complete")
        # a draft can never be completed
        self.assertEqual(self.client.get(reverse("academics:lesson_view", args=[self.draft.pk])).status_code, 403)
        self.assertEqual(LessonProgress.objects.count(), 1)

    def test_student_outside_class_blocked(self):
        self.login("s3")
        self.assertEqual(self.client.get(reverse("academics:course_detail", args=[self.course.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("academics:lesson_view", args=[self.l1.pk])).status_code, 403)
        self.assertEqual(LessonProgress.objects.count(), 0)

    def test_dashboards_and_lists(self):
        self.login("s1")
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "Math")
        self.assertContains(self.client.get(reverse("academics:my_courses")), "Math")
        self.login("t1")
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "Math")
        self.assertContains(self.client.get(reverse("academics:my_courses")), "Class 8")
        self.login("admin")
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)

    def test_parent_sees_only_own_child(self):
        self.login("s1")
        self.client.get(reverse("academics:lesson_view", args=[self.l1.pk]))
        self.login("p1")
        r = self.client.get(reverse("academics:child_progress", args=[self.s1.pk]))
        self.assertContains(r, "1 of 2")
        self.assertEqual(self.client.get(reverse("academics:child_progress", args=[self.s2.pk])).status_code, 403)
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "1 of 2")
        self.login("p2")
        self.assertEqual(self.client.get(reverse("academics:child_progress", args=[self.s1.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)

    def test_youtube_embed_filter(self):
        from core.templatetags.ui import embed
        self.assertEqual(embed("https://www.youtube.com/watch?v=abcdefghijk"), "https://www.youtube.com/embed/abcdefghijk")
        self.assertEqual(embed("https://youtu.be/abcdefghijk"), "https://www.youtube.com/embed/abcdefghijk")
        self.assertEqual(embed("https://example.com"), "")
