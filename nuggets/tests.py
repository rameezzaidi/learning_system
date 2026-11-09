from django.urls import reverse

from exams.tests import Base as ExamBase

from . import engine
from .forms import parse_questions
from .models import Nugget, StudentNugget


class NuggetBase(ExamBase):
    def setUp(self):
        self.fill()  # a: 90%, b: 43.3% (weak), c: 90%
        self.exam.is_published = True
        self.exam.save()


class EngineTests(NuggetBase):
    def test_weak_student_gets_nuggets_and_new_ones_are_created(self):
        st = engine.assign_for_exam(self.exam)
        self.assertEqual(StudentNugget.objects.filter(student=self.a).count(), 0)
        self.assertGreater(StudentNugget.objects.filter(student=self.b).count(), 0)
        self.assertGreater(st["created"], 0)
        n = Nugget.objects.first()
        self.assertEqual(n.source, "auto")
        self.assertTrue(n.points())

    def test_second_run_is_idempotent_and_respects_open_limit(self):
        engine.assign_for_exam(self.exam)
        n1 = StudentNugget.objects.filter(student=self.b).count()
        engine.assign_for_exam(self.exam)
        engine.assign_for_exam(self.exam)
        n2 = StudentNugget.objects.filter(student=self.b).count()
        for c in (self.math, self.eng):
            self.assertLessEqual(StudentNugget.objects.filter(student=self.b, nugget__course=c).exclude(status="done").count(), engine.OPEN_LIMIT)
        self.assertGreaterEqual(n2, n1)

    def test_teacher_made_nugget_preferred(self):
        mine = Nugget.objects.create(course=self.math, topic="Algebra", title="Algebra basics", source="manual",
                                     questions=[{"q": "1+1", "options": ["1", "2"], "answer": 1, "why": ""}])
        engine.assign_for_exam(self.exam)
        self.assertTrue(StudentNugget.objects.filter(student=self.b, nugget=mine).exists())

    def test_check_grading_and_mastery(self):
        n = Nugget.objects.create(course=self.math, topic="T", title="T", questions=[
            {"q": "a", "options": ["x", "y"], "answer": 1}, {"q": "b", "options": ["x", "y"], "answer": 0}])
        c, t, res = engine.grade_check(n, {"q0": "1", "q1": "1"})
        self.assertEqual((c, t), (1, 2))
        row, _ = engine.record(self.b, n, 50)
        self.assertEqual(row.status, "assigned")
        row, _ = engine.record(self.b, n, 100)
        self.assertEqual(row.status, "done")
        self.assertEqual(float(row.score), 100.0)

    def test_low_quiz_sends_nugget(self):
        from assessments.models import Assessment, Attempt
        a = Assessment.objects.create(course=self.math, title="Quiz 1", is_published=True)
        att = Attempt.objects.create(assessment=a, student=self.b, total=10, score=2)
        from django.utils import timezone
        att.submitted_at = timezone.now()
        att.save()
        self.assertEqual(len(engine.assign_after_attempt(att)), 1)


class ViewTests(NuggetBase):
    def test_publish_sends_automatically(self):
        self.exam.is_published = False
        self.exam.save()
        self.login(self.admin)
        self.client.post(reverse("exams:toggle", args=[self.exam.pk, "publish"]))
        self.assertGreater(StudentNugget.objects.filter(student=self.b).count(), 0)

    def test_student_flow(self):
        engine.assign_for_exam(self.exam)
        Nugget.objects.update(review="approved")
        row = StudentNugget.objects.filter(student=self.b).first()
        self.login(self.b)
        self.assertEqual(self.client.get(reverse("nuggets:home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("nuggets:play", args=[row.nugget.pk])).status_code, 200)
        j = self.client.post(reverse("nuggets:check", args=[row.nugget.pk]), {}).json()
        self.assertIn("pct", j)
        self.assertEqual(self.client.post(reverse("nuggets:refresh")).status_code, 302)

    def test_other_class_student_blocked(self):
        n = Nugget.objects.create(course=self.math, topic="T", title="T")
        self.login(self.out)
        self.assertEqual(self.client.get(reverse("nuggets:play", args=[n.pk])).status_code, 403)

    def test_teacher_manage_and_isolation(self):
        n = Nugget.objects.create(course=self.math, topic="T", title="T")
        self.login(self.t_math)
        self.assertEqual(self.client.get(reverse("nuggets:manage")).status_code, 200)
        self.assertEqual(self.client.get(reverse("nuggets:stats", args=[n.pk])).status_code, 200)
        r = self.client.post(reverse("nuggets:assign", args=[n.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StudentNugget.objects.filter(nugget=n).count(), 3)
        self.login(self.t_eng)
        self.assertEqual(self.client.get(reverse("nuggets:stats", args=[n.pk])).status_code, 403)

    def test_generate_and_form(self):
        self.login(self.t_math)
        r = self.client.post(reverse("nuggets:generate"), {"course": self.math.pk, "topic": "Fractions"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Nugget.objects.filter(topic="Fractions").exists())
        r = self.client.post(reverse("nuggets:create"), {"course": self.math.pk, "topic": "Z", "title": "Z nugget", "minutes": 5, "difficulty": 1,
                                                         "is_published": "on", "questions_text": "2+2 | 3 | 4 | 5 | 6 | B | because", "cards_text": "a | b"})
        self.assertEqual(r.status_code, 302)
        z = Nugget.objects.get(title="Z nugget")
        self.assertEqual(z.questions[0]["answer"], 1)
        self.assertEqual(z.cards, [["a", "b"]])

    def test_parse_questions_errors(self):
        qs, errs = parse_questions("only one part | A")
        self.assertTrue(errs and not qs)
        qs, errs = parse_questions("q | x | y | | | C | z")
        self.assertTrue(errs)

    def test_login_required_and_parent_blocked(self):
        self.assertEqual(self.client.get(reverse("nuggets:home")).status_code, 302)
        self.login(self.parent)
        self.assertEqual(self.client.get(reverse("nuggets:home")).status_code, 403)


class EditorAndCoachTests(NuggetBase):
    def test_md_is_safe_and_formats(self):
        from .md import render
        h = render("# Title\n**bold** and *it*\n\n- a\n- b\n\n1. x\n\n> note\n<script>alert(1)</script> $\\frac{1}{2}$ a*b*c")
        self.assertIn("<h3>Title</h3>", h)
        self.assertIn("<strong>bold</strong>", h)
        self.assertIn("<li>a</li>", h)
        self.assertIn("<ol>", h)
        self.assertIn("<blockquote>note</blockquote>", h)
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;script&gt;", h)
        self.assertIn("$\\frac{1}{2}$", h)

    def test_rules_review_flags_gaps(self):
        from .suggest import rules
        r = rules({"explanation": "Short.", "key_points": "", "video_url": "", "cards": [], "questions": []})
        areas = {i["area"] for i in r["improvements"]}
        self.assertTrue({"Explanation", "Key points", "Flashcards", "Quick check", "Engagement"} <= areas)
        self.assertLessEqual(r["score"], 5)

    def test_suggest_view_rules_and_permissions(self):
        self.login(self.t_math)
        r = self.client.post(reverse("nuggets:suggest"), {"course": self.math.pk, "topic": "T", "explanation": "x"})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["source"], "rules")
        self.assertTrue(j["improvements"])
        self.login(self.t_eng)  # not the maths teacher
        self.assertEqual(self.client.post(reverse("nuggets:suggest"), {"course": self.math.pk}).status_code, 404)
        self.login(self.a)
        self.assertEqual(self.client.post(reverse("nuggets:suggest"), {"course": self.math.pk}).status_code, 403)

    def test_suggest_with_ai_is_cleaned(self):
        from unittest import mock
        fake = ('{"score": 7, "summary": "Good", "strengths": ["clear"], "improvements": [{"area": "Quick check", "tip": "add more"}],'
                ' "improved_explanation": "Better **text**", "extra_key_points": ["p1"], "extra_cards": [["f", "b"], "bad"],'
                ' "extra_questions": [{"q": "1+1", "options": ["1", "2"], "answer": 1, "why": "sum"}, {"q": "bad", "options": ["a"], "answer": 5}]}')
        self.login(self.t_math)
        with mock.patch("exams.ai.enabled", return_value=True), mock.patch("exams.ai.call_model", return_value=fake):
            j = self.client.post(reverse("nuggets:suggest"), {"course": self.math.pk, "explanation": "x"}).json()
        self.assertEqual(j["source"], "ai")
        self.assertEqual(j["score"], 7)
        self.assertEqual(j["extra_cards"], [["f", "b"]])
        self.assertEqual(len(j["extra_questions"]), 1)
        self.assertEqual(j["extra_question_lines"][0], "1+1 | 1 | 2 |  |  | B | sum")

    def test_ai_failure_falls_back(self):
        from unittest import mock
        self.login(self.t_math)
        with mock.patch("exams.ai.enabled", return_value=True), mock.patch("exams.ai.call_model", side_effect=RuntimeError("down")):
            j = self.client.post(reverse("nuggets:suggest"), {"course": self.math.pk, "explanation": "x"}).json()
        self.assertEqual(j["source"], "rules")
        self.assertIn("AI unavailable", j["error"])

    def test_play_renders_markup(self):
        n = Nugget.objects.create(course=self.math, topic="T", title="T", explanation="**Bold** idea\n\n- one")
        self.login(self.t_math)
        html = self.client.get(reverse("nuggets:play", args=[n.pk])).content.decode()
        self.assertIn("<strong>Bold</strong>", html)
        self.assertIn("<li>one</li>", html)


class ReviewQueueTests(NuggetBase):
    def test_ai_nuggets_wait_for_review_then_notify_on_approval(self):
        from core.models import Notification
        engine.assign_for_exam(self.exam)
        n = Nugget.objects.filter(assignments__student=self.b).first()
        self.assertEqual(n.review, "pending")
        self.assertFalse(Notification.objects.filter(user=self.b, kind="nugget").exists())   # nothing sent yet
        self.assertTrue(Notification.objects.filter(user=self.t_math, kind="review").exists() or Notification.objects.filter(user=self.t_eng, kind="review").exists())
        row = StudentNugget.objects.get(student=self.b, nugget=n)
        self.login(self.b)
        self.assertEqual(self.client.get(reverse("nuggets:play", args=[n.pk])).status_code, 403)
        self.assertNotIn(row, self.client.get(reverse("nuggets:home")).context["todo"])
        self.login(n.course.teacher)
        self.assertEqual(self.client.get(reverse("nuggets:manage")).context["pending_n"], Nugget.objects.filter(course=n.course, review="pending").count())
        self.client.post(reverse("nuggets:approve", args=[n.pk]))
        n.refresh_from_db()
        self.assertEqual(n.review, "approved")
        self.assertTrue(Notification.objects.filter(user=self.b, kind="nugget").exists())
        self.login(self.b)
        self.assertEqual(self.client.get(reverse("nuggets:play", args=[n.pk])).status_code, 200)

    def test_parent_is_notified_too(self):
        from core.models import Notification
        from accounts.models import User
        par = User.objects.get(username="par")      # linked to student a in the shared fixture
        n = Nugget.objects.create(course=self.math, topic="T", title="T")
        engine.send(self.a, n, "test")
        self.assertTrue(Notification.objects.filter(user=par).exists())
        self.assertTrue(Notification.objects.filter(user=self.a).exists())

    def test_auto_approve_setting(self):
        from core.models import SchoolSettings
        s = SchoolSettings.load(); s.auto_approve_nuggets = True; s.save()
        n = engine.generate_nugget(self.math, "Topic X")
        self.assertEqual(n.review, "approved")

    def test_reject_deletes_draft_and_foreign_teacher_blocked(self):
        n = engine.generate_nugget(self.math, "Draft")
        self.assertEqual(n.review, "pending")
        self.login(self.t_eng)
        self.assertEqual(self.client.post(reverse("nuggets:reject", args=[n.pk])).status_code, 403)
        self.login(self.t_math)
        self.client.post(reverse("nuggets:reject", args=[n.pk]))
        self.assertFalse(Nugget.objects.filter(pk=n.pk).exists())

    def test_editing_a_draft_approves_it(self):
        n = engine.generate_nugget(self.math, "Draft2")
        self.login(self.t_math)
        r = self.client.post(reverse("nuggets:edit", args=[n.pk]), {"course": self.math.pk, "topic": n.topic, "title": "Fixed", "minutes": 5,
                                                                     "difficulty": 1, "is_published": "on", "explanation": "x"})
        self.assertEqual(r.status_code, 302)
        n.refresh_from_db()
        self.assertEqual((n.review, n.title), ("approved", "Fixed"))


class RevisionAndGameTests(NuggetBase):
    def test_spaced_revision_ladder(self):
        from datetime import timedelta
        from django.utils import timezone
        n = Nugget.objects.create(course=self.math, topic="T", title="T", questions=[{"q": "a", "options": ["x", "y"], "answer": 0}])
        today = timezone.localdate()
        row, ex = engine.record(self.b, n, 100)
        self.assertEqual((row.status, row.stage, row.next_review), ("done", 1, today + timedelta(days=3)))
        self.assertEqual(ex["event"], "mastered")
        self.assertFalse(row.due)
        row.next_review = today - timedelta(days=1); row.save()
        self.assertTrue(row.due)
        row, ex = engine.record(self.b, n, 100)
        self.assertEqual((row.stage, row.next_review, ex["event"]), (2, today + timedelta(days=7), "reviewed"))
        row.next_review = today; row.save()
        row, ex = engine.record(self.b, n, 0, missed=[0])
        self.assertEqual((row.stage, row.next_review, ex["event"], row.missed), (1, today + timedelta(days=1), "forgot", [0]))

    def test_xp_streak_badges(self):
        from datetime import timedelta
        from django.utils import timezone
        from . import gamify
        n = Nugget.objects.create(course=self.math, topic="T", title="T")
        row, ex = engine.record(self.b, n, 100)
        st = gamify.stat_for(self.b)
        self.assertEqual(st.streak, 1)
        self.assertGreaterEqual(st.xp, 40)
        keys = {b["key"] for b in ex["new_badges"]}
        self.assertTrue({"first_try", "master_1", "perfect"} <= keys)
        st.last_day = timezone.localdate() - timedelta(days=1); st.streak = 2; st.save()
        gamify.touch(self.b)
        self.assertEqual(gamify.stat_for(self.b).streak, 3)
        st.refresh_from_db(); st.last_day = timezone.localdate() - timedelta(days=3); st.save()
        gamify.touch(self.b)
        self.assertEqual(gamify.stat_for(self.b).streak, 1)

    def test_home_shows_due_and_badge_counts(self):
        from datetime import timedelta
        from django.utils import timezone
        n = Nugget.objects.create(course=self.math, topic="T", title="T")
        row, _ = engine.record(self.b, n, 100)
        row.next_review = timezone.localdate() - timedelta(days=1); row.save()
        self.login(self.b)
        r = self.client.get(reverse("nuggets:home"))
        self.assertEqual([x.pk for x in r.context["due"]], [row.pk])
        self.assertEqual(r.context["nugget_badge"], 1)


class TutorAndInsightsTests(NuggetBase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.n = Nugget.objects.create(course=self.math, topic="Fractions", title="Fractions",
                                       explanation="A fraction has a numerator on top and a denominator at the bottom. Add fractions with the same denominator by adding the numerators.")

    def test_tutor_rules_answer_and_permissions(self):
        self.login(self.a)
        j = self.client.post(reverse("nuggets:tutor", args=[self.n.pk]), {"message": "what is a denominator"}).json()
        self.assertEqual(j["source"], "rules")
        self.assertIn("denominator", j["answer"])
        self.login(self.out)
        self.assertEqual(self.client.post(reverse("nuggets:tutor", args=[self.n.pk]), {"message": "hi"}).status_code, 403)

    def test_tutor_empty_and_rate_limit(self):
        from . import tutor
        self.login(self.a)
        self.assertEqual(self.client.post(reverse("nuggets:tutor", args=[self.n.pk]), {"message": " "}).status_code, 400)
        for _ in range(tutor.HOURLY_LIMIT):
            self.assertEqual(self.client.post(reverse("nuggets:tutor", args=[self.n.pk]), {"message": "numerator"}).status_code, 200)
        self.assertEqual(self.client.post(reverse("nuggets:tutor", args=[self.n.pk]), {"message": "numerator"}).status_code, 429)

    def test_tutor_ai_and_fallback(self):
        from unittest import mock
        self.login(self.a)
        with mock.patch("exams.ai.enabled", return_value=True), mock.patch("exams.ai.call_model", return_value='{"answer": "Think about the bottom number."}'):
            j = self.client.post(reverse("nuggets:tutor", args=[self.n.pk]), {"message": "help"}).json()
        self.assertEqual((j["source"], j["answer"]), ("ai", "Think about the bottom number."))
        with mock.patch("exams.ai.enabled", return_value=True), mock.patch("exams.ai.call_model", side_effect=RuntimeError):
            self.assertEqual(self.client.post(reverse("nuggets:tutor", args=[self.n.pk]), {"message": "numerator"}).json()["source"], "rules")

    def test_insights_access_and_csv(self):
        engine.send(self.b, self.n, "x")
        engine.record(self.b, self.n, 40)
        self.login(self.t_math)
        r = self.client.get(reverse("nuggets:insights") + f"?course={self.math.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["topics"][0]["avg"], 40.0)
        csv = self.client.get(reverse("nuggets:insights") + f"?course={self.math.pk}&csv=1")
        self.assertIn("text/csv", csv["Content-Type"])
        self.assertIn("40.0%", csv.content.decode())
        self.login(self.a)
        self.assertEqual(self.client.get(reverse("nuggets:insights")).status_code, 403)


class NotificationTests(NuggetBase):
    def test_bell_open_read_and_safe_redirect(self):
        from core.models import Notification
        from core.notify import notify
        n = notify(self.a, "Hello", "body", "/nuggets/", "x")
        bad = notify(self.a, "Evil", "body", "https://evil.example/", "x")
        self.login(self.a)
        self.assertEqual(self.client.get(reverse("nuggets:home")).context["bell_unread"], 2)
        r = self.client.get(reverse("core_notification_open", args=[n.pk]))
        self.assertEqual(r["Location"], "/nuggets/")
        r = self.client.get(reverse("core_notification_open", args=[bad.pk]))
        self.assertNotIn("evil", r["Location"])
        self.assertEqual(self.client.get(reverse("core_notifications")).status_code, 200)
        self.client.post(reverse("core_notifications_read"))
        self.assertFalse(Notification.objects.filter(user=self.a, is_read=False).exists())
        self.login(self.b)   # cannot open someone else's
        self.assertEqual(self.client.get(reverse("core_notification_open", args=[n.pk])).status_code, 404)

    def test_results_publish_notifies_students_and_parents(self):
        from core.models import Notification
        self.exam.is_published = False
        self.exam.save()
        self.login(self.admin)
        self.client.post(reverse("exams:toggle", args=[self.exam.pk, "publish"]))
        self.assertTrue(Notification.objects.filter(user=self.a, kind="result").exists())
        self.assertTrue(Notification.objects.filter(user=self.parent, kind="result").exists())

    def test_healthz(self):
        self.assertEqual(self.client.get("/healthz/").json(), {"status": "ok"})


class HardeningTests(NuggetBase):
    def test_login_locks_after_repeated_failures(self):
        from django.core.cache import cache
        cache.clear()
        for _ in range(5):
            r = self.client.post(reverse("accounts:login"), {"username": "a", "password": "wrong"})
            self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("accounts:login"), {"username": "a", "password": "x"})   # even the right password is refused while locked
        self.assertEqual(r.status_code, 429)
        cache.clear()
        self.assertEqual(self.client.post(reverse("accounts:login"), {"username": "a", "password": "x"}).status_code, 302)

    def test_security_headers_and_skip_link(self):
        self.login(self.a)
        r = self.client.get(reverse("nuggets:home"))
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertIn('class="skip"', r.content.decode())
        self.assertIn('id="main"', r.content.decode())
