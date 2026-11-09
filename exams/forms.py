from django import forms

from academics.models import Course
from accounts.forms import StyledMixin

from .models import Exam, ExamPaper, GradeBand


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%d", **kw)


class ExamForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Exam
        fields = ["name", "school_class", "start_date"]
        widgets = {"start_date": DateInput()}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["start_date"].required = False
        self._style()


class PaperForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = ExamPaper
        fields = ["course", "total_marks", "pass_marks", "date"]
        widgets = {"date": DateInput()}

    def __init__(self, *a, exam=None, **k):
        super().__init__(*a, **k)
        self.exam = exam or self.instance.exam
        used = ExamPaper.objects.filter(exam=self.exam).exclude(pk=self.instance.pk).values_list("course_id", flat=True)
        self.fields["course"].queryset = Course.objects.filter(school_class=self.exam.school_class).exclude(pk__in=used).select_related("subject")
        self.fields["course"].label_from_instance = lambda c: f"{c.subject}" + (f" — {c.teacher.display_name}" if c.teacher else " — (no teacher)")
        self.fields["date"].required = False
        self._style()

    def clean(self):
        d = super().clean()
        t, p = d.get("total_marks"), d.get("pass_marks")
        if t is not None and t <= 0:
            self.add_error("total_marks", "Total marks must be more than 0.")
        elif t is not None and p is not None and (p < 0 or p > t):
            self.add_error("pass_marks", "Pass marks must be between 0 and the total.")
        return d


class BandForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = GradeBand
        fields = ["grade", "min_percent", "points", "remark"]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["remark"].required = False
        self._style()

    def clean_min_percent(self):
        v = self.cleaned_data["min_percent"]
        if v < 0 or v > 100:
            raise forms.ValidationError("Between 0 and 100.")
        return v


class AIForm(forms.Form):
    language = forms.ChoiceField(choices=[("en", "English"), ("ur", "Urdu")], initial="en")
