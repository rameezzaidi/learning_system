from django.core.validators import RegexValidator
from django.db import models

from .themes import DEFAULT_THEME, THEME_CHOICES

hex_color = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a colour like #2563eb")


class SchoolSettings(models.Model):
    """Single-row table holding the school's branding and UI choices."""

    FONT_CHOICES = [("sans", "Modern Sans"), ("serif", "Classic Serif"), ("rounded", "Friendly Rounded")]
    RADIUS_CHOICES = [("sharp", "Sharp"), ("soft", "Soft"), ("round", "Round")]
    SIDEBAR_CHOICES = [("themed", "Match theme"), ("light", "Always light"), ("dark", "Always dark")]

    school_name = models.CharField(max_length=120, default="EduPulse Academy")
    tagline = models.CharField(max_length=200, blank=True, default="Learn. Assess. Grow.")
    theme = models.CharField(max_length=30, choices=THEME_CHOICES, default=DEFAULT_THEME)
    use_custom_colors = models.BooleanField(default=False)
    custom_primary = models.CharField(max_length=7, default="#2563eb", validators=[hex_color])
    custom_accent = models.CharField(max_length=7, default="#06b6d4", validators=[hex_color])
    font_style = models.CharField(max_length=10, choices=FONT_CHOICES, default="sans")
    radius = models.CharField(max_length=10, choices=RADIUS_CHOICES, default="soft")
    sidebar_style = models.CharField(max_length=10, choices=SIDEBAR_CHOICES, default="light")
    allow_user_theme = models.BooleanField(
        default=True, help_text="Let teachers, students and parents pick their own theme."
    )
    currency = models.CharField(max_length=6, default="Rs", blank=True, help_text="Shown before every fee amount, e.g. Rs, PKR, $.")
    auto_approve_nuggets = models.BooleanField(
        "Send AI/auto nuggets to students without teacher review", default=False,
        help_text="Off (recommended): AI-made nuggets wait in the review queue until a teacher approves them.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "School settings"
        verbose_name_plural = "School settings"

    def __str__(self):
        return self.school_name

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class Notification(models.Model):
    """In-app notification (bell). Also emailed when the user has an address and EMAIL_NOTIFICATIONS is on."""

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=200, blank=True)
    kind = models.CharField(max_length=20, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "is_read"])]


class AuditLog(models.Model):
    """Who did what, when, from where. Append-only; shown to Super Admin / Head Office."""

    user = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries")
    username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=40, db_index=True)
    target = models.CharField(max_length=160, blank=True)
    detail = models.CharField(max_length=400, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    campus = models.ForeignKey("organization.Campus", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.username} {self.action} {self.target}"
