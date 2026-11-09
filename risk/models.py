from django.conf import settings
from django.db import models


class EarlyWarningSettings(models.Model):
    """One row. The school decides what counts as a warning sign."""
    window_days = models.PositiveSmallIntegerField(default=30, help_text="Attendance is looked at over this many days")
    attendance_below = models.PositiveSmallIntegerField(default=80, help_text="Attendance % under this is a signal")
    exam_below = models.PositiveSmallIntegerField(default=50, help_text="Latest published exam % under this is a signal")
    exam_drop = models.PositiveSmallIntegerField(default=10, help_text="Fall (in % points) from the previous exam that is a signal")
    quiz_below = models.PositiveSmallIntegerField(default=50, help_text="Quiz average % under this is a signal (needs 2+ quizzes)")
    struggling_nuggets = models.PositiveSmallIntegerField(default=2, help_text="Number of nuggets tried 2+ times and still not mastered")
    min_signals = models.PositiveSmallIntegerField(default=1, help_text="Signals needed before an alert is raised")

    class Meta:
        verbose_name_plural = "early warning settings"

    @classmethod
    def get(cls):
        return cls.objects.first() or cls.objects.create()


class Alert(models.Model):
    class Level(models.TextChoices):
        WATCH = "watch", "Watch"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_alerts")
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.WATCH)
    reasons = models.JSONField(default=list)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    resolution_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["student"], condition=~models.Q(status="resolved"), name="one_active_alert_per_student")]

    @property
    def is_active(self):
        return self.status != self.Status.RESOLVED


class Intervention(models.Model):
    """A follow-up task attached to an alert."""

    class Status(models.TextChoices):
        TODO = "todo", "To do"
        DONE = "done", "Done"

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=160)
    detail = models.CharField(max_length=400, blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="risk_tasks")
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.TODO)
    outcome_note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "due_date", "id"]
