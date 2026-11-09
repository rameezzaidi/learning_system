from django.conf import settings
from django.db import models


class Topic(models.Model):
    """One teachable item of a course outline: Unit › Chapter › Topic, with its learning outcome."""

    course = models.ForeignKey("academics.Course", on_delete=models.CASCADE, related_name="topics")
    unit = models.CharField(max_length=120, blank=True)
    chapter = models.CharField(max_length=160, blank=True)
    title = models.CharField(max_length=200)
    outcome = models.TextField("Learning outcome", blank=True)
    position = models.PositiveIntegerField(default=0)
    is_covered = models.BooleanField(default=False)
    covered_on = models.DateField(null=True, blank=True)
    covered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["course_id", "position", "id"]
        indexes = [models.Index(fields=["course", "is_covered"])]

    def __str__(self):
        return self.title


class Handover(models.Model):
    """Academic handover of one course from one teacher to the next. The snapshot freezes the position at that moment."""

    class Kind(models.TextChoices):
        ASSIGNMENT = "assignment", "First assignment"
        TRANSFER = "transfer", "Transfer / replacement"
        ABSENCE = "absence", "Absence cover"

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for acknowledgement"
        ACK = "acknowledged", "Acknowledged"
        CLOSED = "closed", "Closed"

    course = models.ForeignKey("academics.Course", on_delete=models.CASCADE, related_name="handovers")
    from_teacher = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="handovers_out")
    to_teacher = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="handovers_in")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.TRANSFER)
    reason = models.CharField(max_length=300, blank=True)
    expected_return = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    ack_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.course} · {self.get_kind_display()}"
