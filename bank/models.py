from django.conf import settings
from django.db import models


class BankQuestion(models.Model):
    class Kind(models.TextChoices):
        MCQ = "mcq", "Multiple choice"
        TF = "tf", "True / False"
        SHORT = "short", "Short answer"

    course = models.ForeignKey("academics.Course", on_delete=models.CASCADE, related_name="bank_questions")
    topic = models.CharField(max_length=120, blank=True, db_index=True)
    kind = models.CharField(max_length=6, choices=Kind.choices, default=Kind.MCQ)
    text = models.TextField()
    explanation = models.TextField(blank=True)
    accepted = models.CharField(max_length=500, blank=True, help_text="Short answer: accepted answers separated by |")
    difficulty = models.PositiveSmallIntegerField(default=2, choices=[(1, "Easy"), (2, "Medium"), (3, "Hard")])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["topic", "difficulty", "id"]


class BankChoice(models.Model):
    question = models.ForeignKey(BankQuestion, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
