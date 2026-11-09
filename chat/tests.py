import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from exams.tests import Base as ExamBase

from .models import Conversation, Message
from .permissions import allowed_users, can_chat


class ChatPermissionTests(ExamBase):
    def test_rules(self):
        self.assertTrue(can_chat(self.admin, self.out))
        self.assertTrue(can_chat(self.a, self.b))            # classmates
        self.assertTrue(can_chat(self.a, self.t_math))       # class teacher
        self.assertTrue(can_chat(self.a, self.admin))
        self.assertFalse(can_chat(self.a, self.out))         # other class
        self.assertFalse(can_chat(self.a, self.t_none))      # teacher of nothing
        self.assertFalse(can_chat(self.a, self.parent))
        self.assertTrue(can_chat(self.parent, self.t_math))
        self.assertFalse(can_chat(self.parent, self.b))
        self.assertTrue(can_chat(self.t_math, self.a))
        self.assertTrue(can_chat(self.t_math, self.parent))
        self.assertFalse(can_chat(self.t_math, self.out))
        self.assertNotIn(self.a, allowed_users(self.a))


class ChatFlowTests(ExamBase):
    def start(self, user, other):
        self.login(user)
        r = self.client.get(reverse("chat:start", args=[other.pk]))
        self.assertEqual(r.status_code, 302)
        return Conversation.objects.get(pk=int(r.url.rstrip("/").split("/")[-1]))

    def test_direct_dedupes_and_send_receive_read(self):
        c1 = self.start(self.a, self.t_math)
        c2 = self.start(self.t_math, self.a)
        self.assertEqual(c1.pk, c2.pk)
        self.login(self.a)
        r = self.client.post(reverse("chat:send", args=[c1.pk]), {"body": "Salam sir"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Message.objects.count(), 1)
        self.login(self.t_math)
        self.assertEqual(self.client.get(reverse("chat:home")).context["chat_unread"], 1)
        j = self.client.get(reverse("chat:messages", args=[c1.pk])).json()
        self.assertEqual(j["messages"][0]["body"], "Salam sir")
        self.assertEqual(self.client.get(reverse("chat:home")).context["chat_unread"], 0)

    def test_cannot_start_forbidden(self):
        self.login(self.a)
        self.assertEqual(self.client.get(reverse("chat:start", args=[self.out.pk])).status_code, 403)

    def test_non_member_404(self):
        c = self.start(self.a, self.t_math)
        self.login(self.b)
        self.assertEqual(self.client.get(reverse("chat:thread", args=[c.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("chat:send", args=[c.pk]), {"body": "x"}).status_code, 404)

    def test_group_and_blocked_file(self):
        self.login(self.t_math)
        r = self.client.post(reverse("chat:new"), {"users": [self.a.pk, self.b.pk], "title": "Math group"})
        self.assertEqual(r.status_code, 200)
        url = r.json()["url"]
        pk = int(url.rstrip("/").split("/")[-1])
        bad = SimpleUploadedFile("evil.exe", b"MZ")
        r = self.client.post(reverse("chat:send", args=[pk]), {"file": bad})
        self.assertEqual(r.status_code, 400)
        ok = SimpleUploadedFile("note.txt", b"hello")
        r = self.client.post(reverse("chat:send", args=[pk]), {"file": ok, "body": "notes"})
        self.assertEqual(r.status_code, 200)

    def test_empty_message_rejected(self):
        c = self.start(self.a, self.b)
        self.login(self.a)
        self.assertEqual(self.client.post(reverse("chat:send", args=[c.pk]), {"body": "  "}).status_code, 400)

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("chat:home")).status_code, 302)


class ProfileTests(ExamBase):
    def test_student_profile_access_and_terms(self):
        self.fill()
        url = reverse("organization:student_profile", args=[self.a.pk])
        self.login(self.out)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.b)
        self.assertEqual(self.client.get(url).status_code, 403)       # classmate may not view
        for u in (self.admin, self.t_math, self.a, self.parent):
            self.login(u)
            self.assertEqual(self.client.get(url).status_code, 200, u.username)

    def test_unpublished_hidden_from_student_visible_to_staff(self):
        self.fill()
        url = reverse("organization:student_profile", args=[self.a.pk])
        self.login(self.a)
        self.assertEqual(len(self.client.get(url).context["terms"]), 0)
        self.login(self.t_math)
        ctx = self.client.get(url).context
        self.assertEqual(len(ctx["terms"]), 1)
        self.assertEqual(ctx["kpi"]["latest"]["pct"], 90.0)
        self.exam.is_published = True
        self.exam.save()
        self.login(self.a)
        self.assertEqual(len(self.client.get(url).context["terms"]), 1)

    def test_avatar_too_big_rejected(self):
        from accounts.forms import ProfileForm
        big = SimpleUploadedFile("a.png", b"0" * (3 * 1024 * 1024 + 1), content_type="image/png")
        f = ProfileForm({"first_name": "x", "last_name": "y", "email": "a@b.co"}, {"avatar": big}, instance=self.a, allow_theme=False)
        self.assertFalse(f.is_valid())
