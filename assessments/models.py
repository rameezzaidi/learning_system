from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Max, Sum
from django.utils import timezone


class Assessment(models.Model):
    class Kind(models.TextChoices):
        QUIZ = "quiz", "Quiz"
        TEST = "test", "Test"
        EXAM = "exam", "Exam"
        HOMEWORK = "homework", "Homework"

    course = models.ForeignKey("academics.Course", on_delete=models.CASCADE, related_name="assessments")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.QUIZ)
    instructions = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=0, help_text="0 = no time limit")
    max_attempts = models.PositiveIntegerField(default=1, help_text="How many times a student may attempt it")
    due_at = models.DateTimeField(null=True, blank=True, help_text="Optional deadline")
    show_answers = models.BooleanField(default=True, help_text="Show correct answers after submission")
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def total_points(self):
        return self.questions.aggregate(t=Sum("points"))["t"] or Decimal("0")

    @property
    def is_past_due(self):
        return bool(self.due_at and timezone.now() > self.due_at)


class Question(models.Model):
    class Kind(models.TextChoices):
        MCQ = "mcq", "Multiple choice"
        TF = "tf", "True / False"
        SHORT = "short", "Short answer (auto-checked)"
        LONG = "long", "Long answer (teacher marks)"

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="questions")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MCQ)
    text = models.TextField()
    points = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    explanation = models.TextField(blank=True, help_text="Shown with the correct answer after submission")
    accepted = models.CharField(max_length=500, blank=True, help_text="Short answer: accepted answers, separated by |")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.text[:60]

    @property
    def auto_graded(self):
        return self.kind != self.Kind.LONG

    def save(self, *args, **kwargs):
        if not self.position:
            last = Question.objects.filter(assessment=self.assessment).aggregate(m=Max("position"))["m"] or 0
            self.position = last + 1
        super().save(*args, **kwargs)


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.text


class Attempt(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    needs_review = models.BooleanField(default=False, help_text="Has long answers waiting for the teacher")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.student} · {self.assessment}"

    @property
    def submitted(self):
        return self.submitted_at is not None

    @property
    def percent(self):
        return round(float(self.score) * 100 / float(self.total), 1) if self.total else 0

    @property
    def deadline(self):
        if self.assessment.duration_minutes:
            return self.started_at + timedelta(minutes=self.assessment.duration_minutes)
        return None

    @property
    def expired(self):
        d = self.deadline
        return bool(d and timezone.now() > d + timedelta(seconds=30))


class Answer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    choice = models.ForeignKey(Choice, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    text = models.TextField(blank=True)
    points = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                 help_text="Null = not marked yet")
    feedback = models.CharField(max_length=500, blank=True)

    class Meta:
        unique_together = ("attempt", "question")
