import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

SOURCE_CHOICES = [("manual", "Manual"), ("oracle", "Oracle")]


def validate_readonly_sql(value):
    """Sync queries must be a single read-only SELECT (or WITH ... SELECT)."""
    s = (value or "").strip().rstrip(";").strip()
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValidationError("Only SELECT queries are allowed.")
    if ";" in s:
        raise ValidationError("Use one query only, without semicolons.")
    if re.search(r"\b(insert|update|delete|drop|alter|truncate|merge|grant|create|execute|call)\b", low):
        raise ValidationError("Only read-only queries are allowed.")


class _ExternalMixin(models.Model):
    external_id = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")

    class Meta:
        abstract = True

    @property
    def is_external(self):
        return self.source == "oracle"

    def save(self, *args, **kwargs):
        self.external_id = self.external_id or None
        super().save(*args, **kwargs)


class Region(_ExternalMixin):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Campus(_ExternalMixin):
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="campuses")
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["region__name", "name"]
        verbose_name_plural = "campuses"

    def __str__(self):
        return f"{self.name}"


class StudentProfile(models.Model):
    """Extra student data: where the student studies and where the record came from."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile")
    campus = models.ForeignKey(Campus, null=True, blank=True, on_delete=models.SET_NULL, related_name="students")
    admission_no = models.CharField(max_length=40, blank=True)
    external_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        self.external_id = self.external_id or None
        super().save(*args, **kwargs)

    @property
    def is_external(self):
        return self.source == "oracle"

    @property
    def region(self):
        return self.campus.region if self.campus_id else None


DEFAULT_SQL_REGIONS = (
    "SELECT REGION_ID AS external_id, REGION_NAME AS name, REGION_CODE AS code\n"
    "FROM REGIONS"
)
DEFAULT_SQL_CAMPUSES = (
    "SELECT CAMPUS_ID AS external_id, REGION_ID AS region_id, CAMPUS_NAME AS name, CAMPUS_CODE AS code\n"
    "FROM CAMPUSES"
)
DEFAULT_SQL_STUDENTS = (
    "SELECT STUDENT_ID AS external_id, ADMISSION_NO AS admission_no, FIRST_NAME AS first_name,\n"
    "       LAST_NAME AS last_name, EMAIL AS email, PHONE AS phone, CAMPUS_ID AS campus_id\n"
    "FROM STUDENTS"
)


class SyncSettings(models.Model):
    """Single row. Connection credentials stay in environment variables, not in the database."""

    enabled = models.BooleanField(default=False, help_text="Allow automatic background sync.")
    interval_minutes = models.PositiveIntegerField(
        default=60, validators=[MinValueValidator(5)], help_text="How often the automatic sync runs (minimum 5)."
    )
    deactivate_missing = models.BooleanField(
        default=True, help_text="Deactivate Oracle-sourced records that no longer appear in Oracle."
    )
    sql_regions = models.TextField(default=DEFAULT_SQL_REGIONS, validators=[validate_readonly_sql])
    sql_campuses = models.TextField(default=DEFAULT_SQL_CAMPUSES, validators=[validate_readonly_sql])
    sql_students = models.TextField(default=DEFAULT_SQL_STUDENTS, validators=[validate_readonly_sql])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "sync settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class SyncRun(models.Model):
    STATUS = [("running", "Running"), ("success", "Success"), ("partial", "Partial"), ("failed", "Failed")]
    TRIGGER = [("manual", "Manual"), ("auto", "Automatic"), ("command", "Command line")]

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="running")
    trigger = models.CharField(max_length=10, choices=TRIGGER, default="manual")
    stats = models.JSONField(default=dict, blank=True)
    errors = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    @property
    def duration(self):
        if self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds())
        return None
