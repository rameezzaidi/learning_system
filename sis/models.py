import os

from django.conf import settings
from django.db import models


class Admission(models.Model):
    class Status(models.TextChoices):
        INQUIRY = "inquiry", "Inquiry"
        APPLIED = "applied", "Applied"
        INTERVIEW = "interview", "Interview / test"
        ADMITTED = "admitted", "Admitted"
        REJECTED = "rejected", "Not admitted"

    applicant_name = models.CharField(max_length=120)
    date_of_birth = models.DateField(null=True, blank=True)
    guardian_name = models.CharField(max_length=120)
    guardian_phone = models.CharField(max_length=30, blank=True)
    guardian_email = models.EmailField(blank=True)
    previous_school = models.CharField(max_length=160, blank=True)
    campus = models.ForeignKey("organization.Campus", null=True, blank=True, on_delete=models.SET_NULL, related_name="admissions")
    applying_class = models.ForeignKey("academics.SchoolClass", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INQUIRY, db_index=True)
    notes = models.TextField(blank=True)
    student = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="admission")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


DOC_KINDS = [("birth", "Birth certificate / B-Form"), ("cnic", "Guardian CNIC"), ("photo", "Photo"), ("result", "Previous result"),
             ("leaving", "School leaving certificate"), ("medical", "Medical / vaccination"), ("other", "Other")]
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_BYTES = 5 * 1024 * 1024


def private_storage():
    """Documents live outside MEDIA_ROOT so they can never be fetched by URL; they are served by an access-checked view."""
    from django.core.files.storage import FileSystemStorage
    return FileSystemStorage(location=settings.PRIVATE_ROOT)


def doc_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"student_docs/{instance.student_id}/{instance.kind}_{os.urandom(4).hex()}{ext}"


class StudentDocument(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=10, choices=DOC_KINDS, default="other")
    file = models.FileField(upload_to=doc_path, storage=private_storage)
    note = models.CharField(max_length=160, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    @property
    def filename(self):
        return os.path.basename(self.file.name)


class PromotionLog(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="promotions")
    from_class = models.ForeignKey("academics.SchoolClass", null=True, on_delete=models.SET_NULL, related_name="+")
    to_class = models.ForeignKey("academics.SchoolClass", null=True, on_delete=models.SET_NULL, related_name="+")
    on = models.DateField(auto_now_add=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")


class TransferCertificate(models.Model):
    number = models.CharField(max_length=20, unique=True)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="certificates")
    issued_on = models.DateField()
    leaving_class = models.CharField(max_length=60)
    reason = models.CharField(max_length=200, blank=True)
    destination = models.CharField(max_length=160, blank=True)
    conduct = models.CharField(max_length=60, default="Good")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-id"]
