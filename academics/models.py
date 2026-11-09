from django.conf import settings
from django.db import models
from django.db.models import Max


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SchoolClass(models.Model):
    name = models.CharField(max_length=60, help_text="e.g. Class 8")
    section = models.CharField(max_length=20, blank=True, help_text="e.g. A")
    academic_year = models.CharField(max_length=20, blank=True, help_text="e.g. 2026-27")
    campus = models.ForeignKey("organization.Campus", null=True, blank=True, on_delete=models.SET_NULL, related_name="classes",
                               help_text="Leave empty for a class shared by the whole school.")

    class Meta:
        ordering = ["name", "section"]
        unique_together = ("name", "section", "academic_year")
        verbose_name_plural = "classes"

    def __str__(self):
        return f"{self.name} {self.section}".strip()


class Enrollment(models.Model):
    """A student belongs to exactly one class at a time."""

    student = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollment",
        limit_choices_to={"role": "student"},
    )
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="enrollments")
    enrolled_on = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.student} → {self.school_class}"


class Course(models.Model):
    """A subject taught to a class by one teacher."""

    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="courses")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="courses")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="taught_courses", limit_choices_to={"role": "teacher"},
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["school_class__name", "school_class__section", "subject__name"]
        unique_together = ("school_class", "subject")

    def __str__(self):
        return f"{self.subject} · {self.school_class}"

    def published_lessons(self):
        """Published items that sit in a published module."""
        return self.lessons.filter(is_published=True).filter(
            models.Q(module__isnull=True) | models.Q(module__is_published=True))


class Module(models.Model):
    """A section (week / unit / chapter) of a course that groups learning items."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.position:
            last = Module.objects.filter(course=self.course).aggregate(m=Max("position"))["m"] or 0
            self.position = last + 1
        super().save(*args, **kwargs)


class Lesson(models.Model):
    """A learning item inside a module. `kind` decides how it is shown (generic on purpose)."""

    class Kind(models.TextChoices):
        TEXT = "text", "Reading / Notes"
        VIDEO = "video", "Video"
        LINK = "link", "Web link"
        FILE = "file", "File / Handout"
        EMBED = "embed", "Embedded activity (any website / H5P / Wordwall…)"
        GAME = "game", "Built-in game / activity"
        QUIZ = "quiz", "Quiz / Test (from Assessments)"

    class Game(models.TextChoices):
        FLASHCARDS = "flashcards", "Flashcards"
        MEMORY = "memory", "Memory match"
        SCRAMBLE = "scramble", "Word scramble"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons")
    module = models.ForeignKey(Module, null=True, blank=True, on_delete=models.CASCADE, related_name="items")
    assessment = models.ForeignKey("assessments.Assessment", null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    game_type = models.CharField(max_length=12, choices=Game.choices, blank=True)
    game_data = models.TextField(blank=True, help_text="One item per line:  front | back")
    minutes = models.PositiveIntegerField(default=0, help_text="Estimated time in minutes (optional)")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEXT)
    content = models.TextField(blank=True)
    url = models.URLField(blank=True)
    file = models.FileField(upload_to="lessons/%Y/%m/", blank=True)
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["module__position", "position", "id"]

    def __str__(self):
        return self.title

    def game_pairs(self):
        out = []
        for line in self.game_data.splitlines():
            a, _, b = line.partition("|")
            if a.strip() and (b.strip() or self.game_type == self.Game.SCRAMBLE):
                out.append([a.strip(), b.strip()])
        return out

    def save(self, *args, **kwargs):
        if self.module_id is None:  # every item lives in a module
            self.module = (Module.objects.filter(course=self.course).first()
                           or Module.objects.create(course=self.course, title="Module 1"))
        if not self.position:
            last = Lesson.objects.filter(module=self.module).aggregate(m=Max("position"))["m"] or 0
            self.position = last + 1
        super().save(*args, **kwargs)


class LessonProgress(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "lesson")


def progress_for(student, course):
    """Return {'done', 'total', 'pct'} for a student in a course (published lessons only)."""
    ids = list(course.published_lessons().values_list("id", flat=True))
    total = len(ids)
    done = LessonProgress.objects.filter(student=student, lesson_id__in=ids).count()
    return {"done": done, "total": total, "pct": round(done * 100 / total) if total else 0}


def student_class(user):
    e = Enrollment.objects.filter(student=user).select_related("school_class").first()
    return e.school_class if e else None


def course_rows(student, courses):
    """Courses annotated with the student's progress, for list pages."""
    return [{"course": c, **progress_for(student, c)} for c in courses]


def course_outline(course, student=None, manage=False):
    """Modules with their items for the syllabus / player sidebar.

    Students (and parents) only see published modules and items. Each item gets `done`
    when `student` is given; each module gets done/total/pct.
    """
    modules = course.modules.all() if manage else course.modules.filter(is_published=True)
    items = course.lessons.select_related("module", "assessment") if manage else course.published_lessons().select_related("module", "assessment")
    done = set()
    if student is not None:
        done = set(LessonProgress.objects.filter(student=student, lesson__course=course).values_list("lesson_id", flat=True))
    by_module = {}
    for l in items:
        by_module.setdefault(l.module_id, []).append({"lesson": l, "done": l.id in done})
    out = []
    for m in modules:
        its = by_module.get(m.id, [])
        n_done = sum(1 for i in its if i["done"])
        out.append({"module": m, "items": its, "done": n_done, "total": len(its),
                    "pct": round(n_done * 100 / len(its)) if its else 0})
    return out


def next_item(outline):
    """First not-yet-completed published item, else None (course finished / empty)."""
    for m in outline:
        for i in m["items"]:
            if not i["done"]:
                return i["lesson"]
    return None


def first_item(outline):
    for m in outline:
        if m["items"]:
            return m["items"][0]["lesson"]
    return None


class HelpRequest(models.Model):
    """A student asking the teacher for help on a course (optionally on one item)."""

    class Status(models.TextChoices):
        OPEN = "open", "Waiting for teacher"
        ANSWERED = "answered", "Answered"
        RESOLVED = "resolved", "Resolved"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="help_requests")
    lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.SET_NULL, related_name="help_requests")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="help_requests")
    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.subject


class HelpMessage(models.Model):
    request = models.ForeignKey(HelpRequest, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
