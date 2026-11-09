from django.conf import settings
from django.db import models


class GradeBand(models.Model):
    """School-wide grading scale: percentage >= min_percent earns this grade."""

    grade = models.CharField(max_length=5)
    min_percent = models.DecimalField(max_digits=5, decimal_places=2, unique=True)
    points = models.DecimalField(max_digits=3, decimal_places=2, default=0, help_text="GPA points, e.g. 4.0")
    remark = models.CharField(max_length=60, blank=True, help_text="e.g. Excellent")

    class Meta:
        ordering = ["-min_percent"]

    def __str__(self):
        return f"{self.grade} (≥{self.min_percent}%)"


DEFAULT_BANDS = [("A+", 90, "4.0", "Outstanding"), ("A", 80, "3.5", "Excellent"), ("B", 70, "3.0", "Very good"),
                 ("C", 60, "2.0", "Good"), ("D", 50, "1.0", "Satisfactory"), ("F", 0, "0.0", "Needs improvement")]


class Exam(models.Model):
    name = models.CharField(max_length=120, help_text="e.g. Mid Term 2026")
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="exams")
    start_date = models.DateField(null=True, blank=True)
    marks_locked = models.BooleanField(default=False, help_text="Teachers can no longer change marks")
    is_published = models.BooleanField(default=False, help_text="Students and parents can see results")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return f"{self.name} · {self.school_class}"


class ExamPaper(models.Model):
    """One subject's paper inside an exam. The course gives us the subject and the teacher who enters marks."""

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="papers")
    course = models.ForeignKey("academics.Course", on_delete=models.CASCADE, related_name="exam_papers")
    total_marks = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    pass_marks = models.DecimalField(max_digits=6, decimal_places=2, default=33)
    date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["course__subject__name"]
        unique_together = ("exam", "course")

    def __str__(self):
        return f"{self.exam.name} · {self.course.subject}"

    @property
    def subject_name(self):
        return self.course.subject.name


class Mark(models.Model):
    paper = models.ForeignKey(ExamPaper, on_delete=models.CASCADE, related_name="marks")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_marks")
    marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    absent = models.BooleanField(default=False)
    remarks = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("paper", "student")


class AISuggestion(models.Model):
    """Stored guidance for one student (student set) or for the whole class (student null)."""

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="suggestions")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    language = models.CharField(max_length=10, default="en")
    source = models.CharField(max_length=10, default="rules")  # "ai" or "rules"
    model_name = models.CharField(max_length=60, blank=True)
    data = models.JSONField(default=dict)
    error = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now=True)
