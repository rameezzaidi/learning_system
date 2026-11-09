from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from assessments.models import Assessment, Attempt, Choice, Question

from .models import (
    Course, Enrollment, HelpRequest, Lesson, LessonProgress, Module, SchoolClass, Subject, course_outline, next_item,
    progress_for,
)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        mk = User.objects.create_user
        cls.admin = mk("adm", password="x", role="super_admin")
        cls.t1 = mk("t1", password="x", role="teacher")
        cls.t2 = mk("t2", password="x", role="teacher")
        cls.s1 = mk("s1", password="x", role="student")
        cls.s2 = mk("s2", password="x", role="student")
        cls.out = mk("s3", password="x", role="student")
        cls.cls = SchoolClass.objects.create(name="Class 8", section="A")
        other = SchoolClass.objects.create(name="Class 9", section="B")
        for s in (cls.s1, cls.s2):
            Enrollment.objects.create(student=s, school_class=cls.cls)
        Enrollment.objects.create(student=cls.out, school_class=other)
        cls.course = Course.objects.create(school_class=cls.cls, subject=Subject.objects.create(name="Math"), teacher=cls.t1)
        cls.m1 = Module.objects.create(course=cls.course, title="Week 1")
        cls.m2 = Module.objects.create(course=cls.course, title="Week 2")
        cls.a = Lesson.objects.create(course=cls.course, module=cls.m1, title="Read", kind="text", content="hi")
        cls.b = Lesson.objects.create(course=cls.course, module=cls.m1, title="Watch", kind="video", url="https://youtu.be/abcdefghijk")
        cls.g = Lesson.objects.create(course=cls.course, module=cls.m2, title="Cards", kind="game", game_type="flashcards", game_data="a | b\nc | d")

    def login(self, u):
        self.client.force_login(u)


class ModelTests(Base):
    def test_item_without_module_gets_default(self):
        c2 = Course.objects.create(school_class=self.cls, subject=Subject.objects.create(name="Eng"), teacher=self.t1)
        l = Lesson.objects.create(course=c2, title="X", kind="text", content="x")
        self.assertEqual(l.module.title, "Module 1")
        self.assertEqual(Module.objects.filter(course=c2).count(), 1)

    def test_positions_per_module(self):
        self.assertEqual([self.a.position, self.b.position, self.g.position], [1, 2, 1])

    def test_outline_hides_unpublished(self):
        self.m2.is_published = False
        self.m2.save()
        self.b.is_published = False
        self.b.save()
        o = course_outline(self.course, self.s1)
        self.assertEqual([m["module"].title for m in o], ["Week 1"])
        self.assertEqual(o[0]["total"], 1)
        self.assertEqual(progress_for(self.s1, self.course)["total"], 1)
        self.assertEqual(len(course_outline(self.course, manage=True)), 2)

    def test_next_item_and_progress(self):
        LessonProgress.objects.create(student=self.s1, lesson=self.a)
        o = course_outline(self.course, self.s1)
        self.assertEqual(next_item(o), self.b)
        self.assertEqual(o[0]["pct"], 50)

    def test_game_pairs_parse(self):
        self.assertEqual(self.g.game_pairs(), [["a", "b"], ["c", "d"]])


class BuilderTests(Base):
    def test_module_crud_and_order(self):
        self.login(self.t1)
        r = self.client.post(reverse("academics:module_create", args=[self.course.pk]), {"title": "Week 3", "is_published": "on"})
        self.assertEqual(r.status_code, 302)
        m3 = Module.objects.get(title="Week 3")
        self.client.post(reverse("academics:module_move", args=[m3.pk, "up"]))
        self.assertEqual([m.title for m in Module.objects.filter(course=self.course)], ["Week 1", "Week 3", "Week 2"])
        self.client.post(reverse("academics:module_move", args=[m3.pk, "bogus"]))
        self.client.post(reverse("academics:module_toggle", args=[m3.pk]))
        m3.refresh_from_db()
        self.assertFalse(m3.is_published)
        self.client.post(reverse("academics:module_delete", args=[m3.pk]))
        self.assertFalse(Module.objects.filter(pk=m3.pk).exists())

    def test_lesson_move_and_toggle(self):
        self.login(self.t1)
        self.client.post(reverse("academics:lesson_move", args=[self.b.pk, "up"]))
        self.assertEqual([l.title for l in self.m1.items.all()], ["Watch", "Read"])
        self.client.post(reverse("academics:lesson_toggle", args=[self.a.pk]))
        self.a.refresh_from_db()
        self.assertFalse(self.a.is_published)

    def test_permissions(self):
        for u in (self.t2, self.s1):
            self.login(u)
            self.assertEqual(self.client.post(reverse("academics:module_create", args=[self.course.pk]), {"title": "x"}).status_code, 403)
            self.assertEqual(self.client.post(reverse("academics:module_move", args=[self.m1.pk, "down"])).status_code, 403)
            self.assertEqual(self.client.post(reverse("academics:lesson_toggle", args=[self.a.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("academics:module_delete", args=[self.m1.pk])).status_code, 403)

    def post_item(self, **data):
        base = {"title": "T", "is_published": "on"}
        base.update(data)
        self.login(self.t1)
        return self.client.post(reverse("academics:lesson_create", args=[self.course.pk]), base)

    def test_embed_needs_https(self):
        self.assertEqual(self.post_item(kind="embed", url="http://x.com/a").status_code, 200)
        r = self.post_item(kind="embed", url="https://x.com/a", module=self.m2.pk)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Lesson.objects.get(title="T").module, self.m2)

    def test_game_validation(self):
        self.assertEqual(self.post_item(kind="game", game_type="memory", game_data="only one").status_code, 200)
        self.assertEqual(self.post_item(kind="game", game_type="", game_data="a|b\nc|d").status_code, 200)
        self.assertEqual(self.post_item(kind="game", game_type="memory", game_data="a|b\nc|d").status_code, 302)
        self.assertEqual(self.post_item(kind="game", title="S", game_type="scramble", game_data="word").status_code, 302)

    def test_quiz_item_only_from_same_course(self):
        other = Course.objects.create(school_class=self.cls, subject=Subject.objects.create(name="Sci"), teacher=self.t1)
        foreign = Assessment.objects.create(course=other, title="Foreign")
        own = Assessment.objects.create(course=self.course, title="Own")
        self.assertEqual(self.post_item(kind="quiz", assessment=foreign.pk).status_code, 200)
        self.assertEqual(self.post_item(kind="quiz", assessment=own.pk).status_code, 302)
        self.assertEqual(self.post_item(kind="quiz").status_code, 200)

    def test_module_from_other_course_rejected(self):
        other = Course.objects.create(school_class=self.cls, subject=Subject.objects.create(name="Sci"), teacher=self.t1)
        om = Module.objects.create(course=other, title="Other")
        self.assertEqual(self.post_item(kind="text", content="x", module=om.pk).status_code, 200)

    def test_manage_page_renders(self):
        self.login(self.t1)
        r = self.client.get(reverse("academics:course_detail", args=[self.course.pk]))
        self.assertContains(r, "Week 1")
        self.assertContains(r, "Add module")
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("academics:course_detail", args=[self.course.pk])).status_code, 200)


class StudentExperienceTests(Base):
    def test_catalog_continue_button(self):
        LessonProgress.objects.create(student=self.s1, lesson=self.a)
        self.login(self.s1)
        r = self.client.get(reverse("academics:my_courses"))
        row = r.context["rows"][0]
        self.assertEqual(row["continue"], self.b)
        self.assertEqual(row["pct"], 33)
        self.assertContains(r, "Continue")

    def test_course_page_and_hidden_module(self):
        self.m2.is_published = False
        self.m2.save()
        self.login(self.s1)
        r = self.client.get(reverse("academics:course_detail", args=[self.course.pk]))
        self.assertContains(r, "Week 1")
        self.assertNotContains(r, "Week 2")
        self.assertEqual(self.client.get(reverse("academics:lesson_view", args=[self.g.pk])).status_code, 403)

    def test_player_renders_each_kind(self):
        a = Assessment.objects.create(course=self.course, title="Q", is_published=True)
        items = [
            Lesson.objects.create(course=self.course, title="L", kind="link", url="https://example.com"),
            Lesson.objects.create(course=self.course, title="E", kind="embed", url="https://example.com/x"),
            Lesson.objects.create(course=self.course, title="Z", kind="quiz", assessment=a),
            self.a, self.b, self.g,
        ]
        for u in (self.s1, self.t1, self.admin):
            self.login(u)
            for l in items:
                self.assertEqual(self.client.get(reverse("academics:lesson_view", args=[l.pk])).status_code, 200, (u.username, l.kind))

    def test_game_embeds_data_and_done_marks_progress(self):
        self.login(self.s1)
        r = self.client.get(reverse("academics:lesson_view", args=[self.g.pk]))
        self.assertContains(r, 'id="game-data"')
        self.assertContains(r, "flashcards")
        r = self.client.post(reverse("academics:item_done", args=[self.g.pk]))
        self.assertEqual(r.json()["ok"], True)
        self.assertTrue(LessonProgress.objects.filter(student=self.s1, lesson=self.g).exists())
        self.assertEqual(self.client.post(reverse("academics:item_done", args=[self.a.pk])).status_code, 404)  # not a game

    def test_item_done_access(self):
        self.login(self.out)
        self.assertEqual(self.client.post(reverse("academics:item_done", args=[self.g.pk])).status_code, 403)
        self.login(self.t1)
        self.assertEqual(self.client.post(reverse("academics:item_done", args=[self.g.pk])).status_code, 403)

    def test_submitting_quiz_completes_item(self):
        a = Assessment.objects.create(course=self.course, title="Q", is_published=True)
        q = Question.objects.create(assessment=a, kind="mcq", text="?", points=1)
        ok = Choice.objects.create(question=q, text="y", is_correct=True)
        item = Lesson.objects.create(course=self.course, title="Z", kind="quiz", assessment=a)
        self.login(self.s1)
        self.client.post(reverse("assessments:start", args=[a.pk]))
        att = Attempt.objects.get(student=self.s1)
        self.client.post(reverse("assessments:take", args=[att.pk]), {f"q{q.id}": ok.pk})
        self.assertTrue(LessonProgress.objects.filter(student=self.s1, lesson=item).exists())

    def test_other_class_student_blocked(self):
        self.login(self.out)
        self.assertEqual(self.client.get(reverse("academics:course_detail", args=[self.course.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("academics:lesson_view", args=[self.a.pk])).status_code, 403)


class HelpDeskTests(Base):
    def ask(self, user=None, **extra):
        self.login(user or self.s1)
        data = {"body": "I am stuck", "subject": "", **extra}
        return self.client.post(reverse("academics:help_ask", args=[self.course.pk]), data)

    def test_full_conversation(self):
        r = self.ask(lesson=self.a.pk)
        req = HelpRequest.objects.get()
        self.assertRedirects(r, reverse("academics:help_thread", args=[req.pk]))
        self.assertEqual(req.status, "open")
        self.assertEqual(req.lesson, self.a)
        self.assertIn("Read", req.subject)
        # teacher sees and answers
        self.login(self.t1)
        self.assertContains(self.client.get(reverse("academics:help_list")), "Read")
        self.assertEqual(self.client.get(reverse("academics:help_list")).context["help_badge"], 1)
        self.client.post(reverse("academics:help_thread", args=[req.pk]), {"body": "Try step 2"})
        req.refresh_from_db()
        self.assertEqual(req.status, "answered")
        # student gets a badge, follows up, reopens
        self.login(self.s1)
        self.assertEqual(self.client.get(reverse("academics:help_list")).context["help_badge"], 1)
        self.client.post(reverse("academics:help_thread", args=[req.pk]), {"body": "Still confused"})
        req.refresh_from_db()
        self.assertEqual(req.status, "open")
        self.assertEqual(req.messages.count(), 3)
        self.client.post(reverse("academics:help_thread", args=[req.pk]), {"resolve": "1"})
        req.refresh_from_db()
        self.assertEqual(req.status, "resolved")

    def test_privacy(self):
        self.ask()
        req = HelpRequest.objects.get()
        for u in (self.s2, self.t2, self.out):
            self.login(u)
            self.assertEqual(self.client.get(reverse("academics:help_thread", args=[req.pk])).status_code, 403, u.username)
            self.assertNotContains(self.client.get(reverse("academics:help_list")), req.subject)
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("academics:help_thread", args=[req.pk])).status_code, 200)

    def test_only_enrolled_students_can_ask(self):
        self.assertEqual(self.ask(self.out).status_code, 403)
        self.assertEqual(self.ask(self.t1).status_code, 403)
        self.assertEqual(HelpRequest.objects.count(), 0)

    def test_empty_question_rejected(self):
        self.login(self.s1)
        self.client.post(reverse("academics:help_ask", args=[self.course.pk]), {"body": "  "})
        self.assertEqual(HelpRequest.objects.count(), 0)

    def test_status_filter(self):
        self.ask()
        self.login(self.t1)
        self.assertEqual(len(self.client.get(reverse("academics:help_list"), {"status": "open"}).context["items"]), 1)
        self.assertEqual(len(self.client.get(reverse("academics:help_list"), {"status": "resolved"}).context["items"]), 0)


class AutoCompleteTests(Base):
    def done(self, user, lesson):
        return LessonProgress.objects.filter(student=user, lesson=lesson).exists()

    def test_open_completes_text_link_file_embed(self):
        items = [
            self.a,
            Lesson.objects.create(course=self.course, title="L", kind="link", url="https://example.com"),
            Lesson.objects.create(course=self.course, title="E", kind="embed", url="https://example.com/x"),
            Lesson.objects.create(course=self.course, title="F", kind="file"),
            Lesson.objects.create(course=self.course, title="V2", kind="video", url="https://vimeo.com/123"),
        ]
        self.login(self.s1)
        for l in items:
            self.assertFalse(self.done(self.s1, l))
            self.client.get(reverse("academics:lesson_view", args=[l.pk]))
            self.assertTrue(self.done(self.s1, l), l.kind)

    def test_youtube_game_quiz_do_not_complete_on_open(self):
        a = Assessment.objects.create(course=self.course, title="Q", is_published=True)
        quiz = Lesson.objects.create(course=self.course, title="Z", kind="quiz", assessment=a)
        self.login(self.s1)
        for l in (self.b, self.g, quiz):  # b is a YouTube video
            self.client.get(reverse("academics:lesson_view", args=[l.pk]))
            self.assertFalse(self.done(self.s1, l), l.kind)

    def test_youtube_completes_via_done_endpoint(self):
        self.login(self.s1)
        self.assertEqual(self.client.post(reverse("academics:item_done", args=[self.b.pk])).status_code, 200)
        self.assertTrue(self.done(self.s1, self.b))

    def test_teacher_and_admin_viewing_never_completes(self):
        for u in (self.t1, self.admin):
            self.login(u)
            self.client.get(reverse("academics:lesson_view", args=[self.a.pk]))
        self.assertEqual(LessonProgress.objects.count(), 0)

    def test_unpublished_or_hidden_never_completes(self):
        self.a.is_published = False
        self.a.save()
        self.login(self.s1)
        self.assertEqual(self.client.get(reverse("academics:lesson_view", args=[self.a.pk])).status_code, 403)
        self.assertEqual(LessonProgress.objects.count(), 0)

    def test_no_manual_button_anywhere(self):
        self.login(self.s1)
        for l in (self.a, self.b, self.g):
            self.assertNotContains(self.client.get(reverse("academics:lesson_view", args=[l.pk])), "Mark as complete")

    def test_next_item_moves_on_after_open(self):
        self.login(self.s1)
        self.client.get(reverse("academics:lesson_view", args=[self.a.pk]))
        r = self.client.get(reverse("academics:my_courses"))
        self.assertEqual(r.context["rows"][0]["continue"], self.b)
