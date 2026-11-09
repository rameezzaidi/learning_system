import time

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog

from . import twofa
from .models import TwoFactor, User, UserSession


def mk(username, role="teacher", **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


class TotpTests(TestCase):
    def test_rfc6238_vector(self):
        # RFC 6238 test secret "12345678901234567890" (base32) at T=59 -> 94287082 (8 digits); 6-digit tail is 287082
        import base64
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(twofa._hotp(secret, 59 // 30, 8), "94287082")
        self.assertEqual(twofa.totp(secret, at=59), "287082")

    def test_verify_window_and_garbage(self):
        s = twofa.new_secret()
        now = time.time()
        self.assertTrue(twofa.verify(s, twofa.totp(s, at=now), at=now))
        self.assertTrue(twofa.verify(s, twofa.totp(s, at=now - 30), at=now))  # one step of clock drift
        self.assertFalse(twofa.verify(s, twofa.totp(s, at=now - 300), at=now))
        for bad in ("", None, "abc", "12345", "1234567"):
            self.assertFalse(twofa.verify(s, bad))

    def test_backup_hash_normalises(self):
        self.assertEqual(twofa.hash_code("ABCD-1234"), twofa.hash_code("abcd1234"))


class FlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.u = mk("alice")

    def enable(self):
        tf = TwoFactor.objects.create(user=self.u, secret=twofa.new_secret(), enabled=True, backup_hashes=[twofa.hash_code("aaaa-bbbb")])
        return tf

    def test_setup_requires_valid_code_and_shows_backup_codes(self):
        self.client.force_login(self.u)
        self.client.get(reverse("accounts:twofa_setup"))
        tf = TwoFactor.objects.get(user=self.u)
        self.assertFalse(tf.enabled)
        self.client.post(reverse("accounts:twofa_setup"), {"code": "000000"})
        tf.refresh_from_db()
        self.assertFalse(tf.enabled)
        r = self.client.post(reverse("accounts:twofa_setup"), {"code": twofa.totp(tf.secret)})
        tf.refresh_from_db()
        self.assertTrue(tf.enabled)
        self.assertEqual(len(tf.backup_hashes), 8)
        self.assertContains(r, "Save your backup codes")
        self.assertTrue(AuditLog.objects.filter(action="2fa.enabled").exists())

    def test_login_requires_second_step(self):
        tf = self.enable()
        r = self.client.post(reverse("accounts:login"), {"username": "alice", "password": "pw-Test-12345"})
        self.assertRedirects(r, reverse("accounts:verify2fa"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)  # not signed in yet
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)
        r = self.client.post(reverse("accounts:verify2fa"), {"code": "123456"})
        self.assertContains(r, "not right")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.client.post(reverse("accounts:verify2fa"), {"code": twofa.totp(tf.secret)})
        self.assertIn("_auth_user_id", self.client.session)
        self.assertTrue(UserSession.objects.filter(user=self.u).exists())

    def test_backup_code_works_once(self):
        self.enable()
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": "pw-Test-12345"})
        self.client.post(reverse("accounts:verify2fa"), {"code": "AAAA-BBBB"})
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(TwoFactor.objects.get().backup_hashes, [])
        self.client.post(reverse("accounts:logout"))
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": "pw-Test-12345"})
        self.client.post(reverse("accounts:verify2fa"), {"code": "aaaa-bbbb"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_codes_lock_out_and_wrong_password_never_reaches_step_two(self):
        tf = self.enable()
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": "nope"})
        self.assertNotIn("pre2fa", self.client.session)
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": "pw-Test-12345"})
        for _ in range(5):
            self.client.post(reverse("accounts:verify2fa"), {"code": "000000"})
        r = self.client.post(reverse("accounts:verify2fa"), {"code": twofa.totp(tf.secret)})  # right code, but locked
        self.assertContains(r, "Too many")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verify_without_pending_login_redirects(self):
        self.assertRedirects(self.client.get(reverse("accounts:verify2fa")), reverse("accounts:login"), fetch_redirect_response=False)

    def test_disable_needs_password(self):
        self.enable()
        self.client.force_login(self.u)
        self.client.post(reverse("accounts:twofa_disable"), {"password": "wrong"})
        self.assertTrue(TwoFactor.objects.exists())
        self.client.post(reverse("accounts:twofa_disable"), {"password": "pw-Test-12345"})
        self.assertFalse(TwoFactor.objects.exists())

    def test_required_roles_are_pushed_to_setup(self):
        with override_settings(REQUIRE_2FA_ROLES=("teacher",)):
            self.client.force_login(self.u)
            self.assertRedirects(self.client.get(reverse("accounts:dashboard")), reverse("accounts:twofa_setup"), fetch_redirect_response=False)
            self.assertEqual(self.client.get(reverse("accounts:security")).status_code, 200)
            self.client.post(reverse("accounts:twofa_disable"), {"password": "pw-Test-12345"})
            self.enable()
            self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)
            self.client.post(reverse("accounts:twofa_disable"), {"password": "pw-Test-12345"})
            self.assertTrue(TwoFactor.objects.exists())  # required role cannot turn it off

    def test_sessions_list_and_revoke(self):
        from django.contrib.sessions.models import Session
        from django.test import Client
        other = Client()
        other.force_login(self.u)
        other.get(reverse("accounts:dashboard"))
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": "pw-Test-12345"})
        self.assertEqual(UserSession.objects.filter(user=self.u).count(), 2)
        r = self.client.post(reverse("accounts:security"), {"action": "revoke_others"})
        self.assertEqual(UserSession.objects.filter(user=self.u).count(), 1)
        self.assertEqual(other.get(reverse("accounts:dashboard")).status_code, 302)  # signed out
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)  # this one survives
        # cannot revoke someone else's session
        bob = mk("bob")
        b = Client()
        b.force_login(bob)
        b.get("/")
        bs = UserSession.objects.filter(user=bob).first()
        if bs:
            self.client.post(reverse("accounts:security"), {"action": "revoke", "id": bs.pk})
            self.assertTrue(Session.objects.filter(session_key=bs.session_key).exists())
