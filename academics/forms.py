from django import forms

from accounts.forms import StyledMixin
from accounts.models import User

from assessments.models import Assessment

from .models import Course, Lesson, Module, SchoolClass, Subject


class ClassForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ["name", "section", "academic_year"]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()


class SubjectForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["name", "code"]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()


class CourseForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Course
        fields = ["subject", "teacher", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["teacher"].queryset = User.objects.filter(role=User.Role.TEACHER, is_active=True)
        self.fields["teacher"].empty_label = "— Not assigned yet —"
        self._style()


class EnrollForm(StyledMixin, forms.Form):
    students = forms.ModelMultipleChoiceField(queryset=User.objects.none(), label="Add students")

    def __init__(self, school_class, *a, **k):
        super().__init__(*a, **k)
        self.fields["students"].queryset = (
            User.objects.filter(role=User.Role.STUDENT, is_active=True).exclude(enrollment__school_class=school_class)
        )
        self.fields["students"].help_text = "Hold Ctrl (or Cmd) to select several. A student already in another class is moved here."
        self._style()


class ModuleForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Module
        fields = ["title", "description", "is_published"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["title"].help_text = "e.g. Week 1 · Fractions"
        self._style()


class LessonForm(StyledMixin, forms.ModelForm):
    """One form for every kind of learning item; the template shows only the fields that apply."""

    class Meta:
        model = Lesson
        fields = ["title", "module", "kind", "content", "url", "file", "assessment", "game_type", "game_data",
                  "minutes", "position", "is_published"]
        widgets = {"content": forms.Textarea(attrs={"rows": 5}), "game_data": forms.Textarea(attrs={"rows": 7})}

    def __init__(self, *a, course=None, **k):
        super().__init__(*a, **k)
        course = course or (self.instance.course if self.instance.pk else None)
        self.fields["module"].queryset = Module.objects.filter(course=course) if course else Module.objects.none()
        self.fields["module"].required = False
        self.fields["module"].empty_label = "— First module —"
        self.fields["assessment"].queryset = Assessment.objects.filter(course=course) if course else Assessment.objects.none()
        self.fields["assessment"].required = False
        self.fields["assessment"].empty_label = "— Choose a quiz —"
        self.fields["assessment"].help_text = "Create quizzes under Assessments first. Students complete this item by submitting the quiz."
        self.fields["game_type"].required = False
        self.fields["game_type"].choices = [("", "— Choose a game —")] + list(Lesson.Game.choices)
        self.fields["position"].required = False
        self.fields["minutes"].required = False
        self.fields["content"].label = "Description / notes"
        self.fields["content"].help_text = "Main text for readings; optional instructions for every other kind."
        self.fields["url"].help_text = "Video (YouTube works), web link, or the https address of the embedded activity."
        self.fields["game_data"].help_text = ("One per line as  front | back  (flashcards, memory match). "
                                              "Word scramble: word | hint.")
        self._style()

    def clean_minutes(self):
        return self.cleaned_data.get("minutes") or 0

    def clean(self):
        d = super().clean()
        kind = d.get("kind")
        K = Lesson.Kind
        if kind in (K.VIDEO, K.LINK, K.EMBED) and not d.get("url"):
            self.add_error("url", "Please enter the link for this item.")
        if kind == K.EMBED and d.get("url") and not d["url"].lower().startswith("https://"):
            self.add_error("url", "Embedded activities must use a secure https:// address.")
        if kind == K.FILE and not d.get("file") and not (self.instance and self.instance.file):
            self.add_error("file", "Please upload a file.")
        if kind == K.TEXT and not d.get("content"):
            self.add_error("content", "Please write the content.")
        if kind == K.QUIZ and not d.get("assessment"):
            self.add_error("assessment", "Choose the quiz for this item.")
        if kind == K.GAME:
            gt = d.get("game_type")
            if not gt:
                self.add_error("game_type", "Choose a game.")
            else:
                probe = Lesson(game_type=gt, game_data=d.get("game_data", ""))
                n = len(probe.game_pairs())
                need = 1 if gt == Lesson.Game.SCRAMBLE else 2
                if n < need:
                    self.add_error("game_data", f"Add at least {need} line(s) in the form  front | back.")
                elif gt == Lesson.Game.MEMORY and n > 12:
                    self.add_error("game_data", "Memory match supports up to 12 pairs.")
        return d


class HelpForm(StyledMixin, forms.Form):
    subject = forms.CharField(max_length=200, required=False, label="Topic")
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Your question")

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["subject"].widget.attrs["placeholder"] = "Short title (optional)"
        self.fields["body"].widget.attrs["placeholder"] = "What are you stuck on?"
        self._style()


class ReplyForm(StyledMixin, forms.Form):
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), label="Reply")

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()
