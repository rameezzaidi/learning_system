import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from academics.models import Course, Enrollment, SchoolClass, Subject
from accounts.models import User
from core.models import AuditLog
from organization.models import Campus, Region, StudentProfile

from . import services
from .models import Admission, PromotionLog, StudentDocument, TransferCertificate

TMP = tempfile.mkdtemp()


def mk(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role, first_name=username, **kw)


@override_settings(PRIVATE_ROOT=TMP)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        reg = Region.objects.create(name="South")
        self.c1, self.c2 = Campus.objects.create(region=reg, name="Alpha"), Campus.objects.create(region=reg, name="Beta")
        self.cls8 = SchoolClass.objects.create(name="Class 8", section="A", campus=self.c1)
        self.cls9 = SchoolClass.objects.create(name="Class 9", section="A", campus=self.c1)
        self.cls_b = SchoolClass.objects.create(name="Class 8", section="B", campus=self.c2)
        self.admin, self.head = mk("adm", "super_admin"), mk("head", "head_office")
        self.prin, self.prin2 = mk("prin", "principal", campus=self.c1), mk("prin2", "principal", campus=self.c2)
        self.reg = mk("regd", "regional_director", region=reg)
        self.teacher = mk("t1", "teacher", campus=self.c1)
        self.s1, self.s2 = mk("s1", "student"), mk("s2", "student")
        for s, cl, c in ((self.s1, self.cls8, self.c1), (self.s2, self.cls_b, self.c2)):
            Enrollment.objects.create(student=s, school_class=cl)
            StudentProfile.objects.create(user=s, campus=c, admission_no=s.username)
        self.parent = mk("par", "parent")
        self.parent.children.set([self.s1])


class AdmissionTests(Base):
    def mkadm(self, **kw):
        d = dict(applicant_name="Ayaan Raza", guardian_name="Raza Khan", guardian_email="r@x.com", campus=self.c1, applying_class=self.cls8)
        d.update(kw)
        return Admission.objects.create(**d)

    def test_admit_creates_everything_once(self):
        a = self.mkadm()
        st, pw, par, ppw = services.admit(a, self.prin)
        a.refresh_from_db()
        self.assertEqual((a.status, a.student), ("admitted", st))
        self.assertTrue(st.check_password(pw))
        self.assertEqual(Enrollment.objects.get(student=st).school_class, self.cls8)
        self.assertEqual(st.student_profile.campus, self.c1)
        self.assertTrue(st.student_profile.admission_no.startswith("ADM-"))
        self.assertIn(st, par.children.all())
        with self.assertRaises(ValueError):
            services.admit(a, self.prin)

    def test_admit_needs_class_and_unique_usernames(self):
        with self.assertRaises(ValueError):
            services.admit(self.mkadm(applying_class=None), self.prin)
        a1, a2 = self.mkadm(), self.mkadm()
        u1 = services.admit(a1, self.prin, create_parent=False)[0].username
        u2 = services.admit(a2, self.prin, create_parent=False)[0].username
        self.assertNotEqual(u1, u2)

    def test_view_flow_and_credentials_shown_once(self):
        self.client.force_login(self.prin)
        a = self.mkadm()
        r = self.client.post(reverse("sis:admission", args=[a.pk]), {"action": "admit", "create_parent": "on"}, follow=True)
        self.assertContains(r, "shown once")
        self.assertNotContains(self.client.get(reverse("sis:admission", args=[a.pk])), "shown once")
        self.assertTrue(AuditLog.objects.filter(action="admission.admit").exists())

    def test_scope_and_permissions(self):
        a = self.mkadm()
        self.client.force_login(self.prin2)
        self.assertEqual(self.client.get(reverse("sis:admission", args=[a.pk])).status_code, 404)
        for u in (self.teacher, self.s1, self.parent):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("sis:admissions")).status_code, 403, u.username)
        self.client.force_login(self.reg)  # can view, cannot manage
        self.assertEqual(self.client.get(reverse("sis:admission", args=[a.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("sis:admission", args=[a.pk]), {"action": "admit"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("sis:admission_new")).status_code, 403)

    def test_new_inquiry_scoped_class_choice(self):
        self.client.force_login(self.prin)
        self.client.post(reverse("sis:admission_new"), {"applicant_name": "X Y", "guardian_name": "G", "applying_class": self.cls_b.pk, "campus": self.c2.pk})
        a = Admission.objects.get()
        self.assertIsNone(a.applying_class)  # other campus's class/campus is ignored
        self.assertIsNone(a.campus)
        self.client.post(reverse("sis:admission_new"), {"applicant_name": "", "guardian_name": "G"})
        self.assertEqual(Admission.objects.count(), 1)


class DocumentTests(Base):
    def pdf(self, name="b.pdf", body=b"%PDF-1.4 test"):
        return SimpleUploadedFile(name, body, content_type="application/pdf")

    def test_upload_view_delete_and_validation(self):
        self.client.force_login(self.prin)
        url = reverse("sis:documents", args=[self.s1.pk])
        self.client.post(url, {"kind": "birth", "file": self.pdf()})
        d = StudentDocument.objects.get()
        self.assertTrue(d.file.name.startswith(f"student_docs/{self.s1.pk}/birth_"))
        r = self.client.get(reverse("sis:document_file", args=[d.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 test")
        self.assertTrue(AuditLog.objects.filter(action="document.view").exists())
        self.client.post(url, {"kind": "other", "file": SimpleUploadedFile("x.exe", b"MZ")})
        self.client.post(url, {"kind": "other", "file": SimpleUploadedFile("fake.pdf", b"not a pdf")})
        self.client.post(url, {"kind": "other", "file": SimpleUploadedFile("big.pdf", b"%PDF" + b"0" * (5 * 1024 * 1024 + 1))})
        self.assertEqual(StudentDocument.objects.count(), 1)
        self.client.post(url, {"action": "delete", "id": d.pk})
        self.assertEqual(StudentDocument.objects.count(), 0)

    def test_documents_are_not_publicly_served_and_scoped(self):
        self.client.force_login(self.prin)
        self.client.post(reverse("sis:documents", args=[self.s1.pk]), {"kind": "birth", "file": self.pdf()})
        d = StudentDocument.objects.get()
        from django.conf import settings
        self.assertNotIn(str(settings.MEDIA_ROOT), d.file.path)
        for u in (self.prin2, self.teacher, self.s1, self.parent):
            self.client.force_login(u)
            self.assertIn(self.client.get(reverse("sis:document_file", args=[d.pk])).status_code, (403, 404), u.username)
            self.assertIn(self.client.get(reverse("sis:documents", args=[self.s1.pk])).status_code, (403, 404), u.username)
        self.client.force_login(self.reg)  # view yes, upload no
        self.assertEqual(self.client.get(reverse("sis:documents", args=[self.s1.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("sis:documents", args=[self.s1.pk]), {"kind": "other", "file": self.pdf()}).status_code, 403)


class PromotionTests(Base):
    def test_promote_logs_and_keeps_history(self):
        self.client.force_login(self.prin)
        r = self.client.post(reverse("sis:promotion"), {"from": self.cls8.pk, "to": self.cls9.pk, "student": [self.s1.pk, self.s2.pk]})  # s2 is not in cls8
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Enrollment.objects.get(student=self.s1).school_class, self.cls9)
        self.assertEqual(Enrollment.objects.get(student=self.s2).school_class, self.cls_b)  # untouched
        self.assertEqual(PromotionLog.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="promotion").exists())

    def test_cannot_promote_across_campus_or_same_class(self):
        self.client.force_login(self.prin)
        self.client.post(reverse("sis:promotion"), {"from": self.cls_b.pk, "to": self.cls9.pk, "student": [self.s2.pk]})  # source out of scope
        self.assertEqual(PromotionLog.objects.count(), 0)
        self.client.post(reverse("sis:promotion"), {"from": self.cls8.pk, "to": self.cls8.pk, "student": [self.s1.pk]})
        self.assertEqual(PromotionLog.objects.count(), 0)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("sis:promotion")).status_code, 403)


class TransferCertificateTests(Base):
    def test_issue_deactivates_and_numbers(self):
        self.client.force_login(self.prin)
        url = reverse("sis:tc_issue", args=[self.s1.pk])
        self.client.post(url, {"reason": "Moving"})  # no confirm
        self.assertEqual(TransferCertificate.objects.count(), 0)
        r = self.client.post(url, {"reason": "Moving", "destination": "ABC School", "confirm": "on"})
        t = TransferCertificate.objects.get()
        self.assertRedirects(r, reverse("sis:tc", args=[t.pk]))
        self.s1.refresh_from_db()
        self.assertFalse(self.s1.is_active)
        self.assertEqual((t.number, t.leaving_class), ("TC-0001", "Class 8 A"))
        self.assertContains(self.client.get(reverse("sis:tc", args=[t.pk])), "TC-0001")
        self.client.force_login(self.prin2)
        self.assertEqual(self.client.get(reverse("sis:tc", args=[t.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("sis:tc_issue", args=[self.s1.pk]), {"confirm": "on"}).status_code, 403)
