from django.conf import settings
from django.db import models

WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday")]


class Period(models.Model):
    """One row of the school's bell schedule."""
    name = models.CharField(max_length=40, help_text="e.g. Period 1, Break")
    start_time = models.TimeField()
    end_time = models.TimeField()
    order = models.PositiveSmallIntegerField(unique=True)
    is_break = models.BooleanField(default=False, help_text="Breaks have no lessons")

    class Meta:
        ordering = ["order"]
        constraints = [models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")), name="period_times_ordered")]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"


class Slot(models.Model):
    """A class has one course in one period on one weekday."""
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="slots")
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    period = models.ForeignKey(Period, on_delete=models.CASCADE, related_name="slots")
    course = models.ForeignKey("academics.Course", on_delete=models.CASCADE, related_name="slots")
    room = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["weekday", "period__order"]
        unique_together = ("school_class", "weekday", "period")

    @property
    def teacher(self):
        return self.course.teacher


class Substitution(models.Model):
    """Cover for one slot on one date."""
    slot = models.ForeignKey(Slot, on_delete=models.CASCADE, related_name="substitutions")
    date = models.DateField(db_index=True)
    substitute = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="substitutions")
    reason = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "slot__period__order"]
        unique_together = ("slot", "date")


class Term(models.Model):
    name = models.CharField(max_length=60, help_text="e.g. Term 1 2026-27")
    start_date = models.DateField()
    end_date = models.DateField()
    campus = models.ForeignKey("organization.Campus", null=True, blank=True, on_delete=models.CASCADE, related_name="terms",
                               help_text="Leave empty for all campuses")

    class Meta:
        ordering = ["start_date"]
        constraints = [models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")), name="term_dates_ordered")]

    def __str__(self):
        return self.name


class CalendarEvent(models.Model):
    class Kind(models.TextChoices):
        HOLIDAY = "holiday", "Holiday / closure"
        EXAM = "exam", "Exam"
        EVENT = "event", "School event"
        MEETING = "meeting", "Parent-teacher meeting"
        OTHER = "other", "Other"

    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.EVENT)
    title = models.CharField(max_length=120)
    start_date = models.DateField(db_index=True)
    end_date = models.DateField()
    campus = models.ForeignKey("organization.Campus", null=True, blank=True, on_delete=models.CASCADE, related_name="events",
                               help_text="Leave empty for all campuses")
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["start_date", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")), name="event_dates_ordered")]
