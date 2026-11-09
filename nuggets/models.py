from django.conf import settings
from django.db import models


class Nugget(models.Model):
    """A short micro-lesson (3-8 min) on ONE idea: explanation, key points, flashcards and a quick check."""

    class Source(models.TextChoices):
        MANUAL = "manual", "Teacher"
        AI = "ai", "AI"
        AUTO = "auto", "Auto"

    course = models.ForeignKey("academics.Course", on_delete=models.CASCADE, related_name="nuggets")
    topic = models.CharField(max_length=120, help_text="The single idea this nugget teaches, e.g. Fractions")
    title = models.CharField(max_length=200)
    explanation = models.TextField(blank=True, help_text="Short, simple explanation (plain text)")
    key_points = models.TextField(blank=True, help_text="One key point per line")
    video_url = models.URLField(blank=True)
    minutes = models.PositiveIntegerField(default=5)
    difficulty = models.PositiveSmallIntegerField(default=1, choices=[(1, "Easy"), (2, "Medium"), (3, "Hard")])
    cards = models.JSONField(default=list, blank=True)       # [[front, back], ...]
    questions = models.JSONField(default=list, blank=True)   # [{"q", "options": [...], "answer": 0, "why"}, ...]
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    is_published = models.BooleanField(default=True)
    review = models.CharField(max_length=8, default="approved", choices=[("approved", "Approved"), ("pending", "Needs review")],
                              help_text="AI/auto nuggets stay hidden from students until a teacher approves them")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title

    @property
    def live(self):
        """Visible to students."""
        return self.is_published and self.review == "approved"

    def points(self):
        return [p.strip() for p in self.key_points.splitlines() if p.strip()]


class StudentNugget(models.Model):
    """A nugget sent to one student, and how they got on."""

    class Trigger(models.TextChoices):
        EXAM = "exam", "Weak in an exam"
        QUIZ = "quiz", "Low quiz score"
        MANUAL = "manual", "Sent by teacher"
        SELF = "self", "Recommended"

    class Status(models.TextChoices):
        ASSIGNED = "assigned", "To do"
        DONE = "done", "Mastered"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="nugget_tasks")
    nugget = models.ForeignKey(Nugget, on_delete=models.CASCADE, related_name="assignments")
    reason = models.CharField(max_length=250, blank=True)
    trigger = models.CharField(max_length=8, choices=Trigger.choices, default=Trigger.SELF)
    exam = models.ForeignKey("exams.Exam", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ASSIGNED)
    score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, help_text="Best quick-check %")
    attempts = models.PositiveIntegerField(default=0)
    seen = models.BooleanField(default=False)
    stage = models.PositiveSmallIntegerField(default=0, help_text="Spaced-revision step (0 = not mastered yet)")
    next_review = models.DateField(null=True, blank=True)
    missed = models.JSONField(default=list, blank=True, help_text="Question numbers missed in the last try")
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("student", "nugget")
        ordering = ["status", "-assigned_at"]

    @property
    def due(self):
        from django.utils import timezone
        return self.status == self.Status.DONE and self.next_review is not None and self.next_review <= timezone.localdate()


class LearnerStat(models.Model):
    """Points, daily streak and badges for one student."""

    student = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learner_stat")
    xp = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    best_streak = models.PositiveIntegerField(default=0)
    last_day = models.DateField(null=True, blank=True)
    badges = models.JSONField(default=list, blank=True)

    @property
    def level(self):
        return 1 + self.xp // 100
