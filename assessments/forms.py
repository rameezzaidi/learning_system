from django import forms

from accounts.forms import StyledMixin

from .models import Assessment, Choice, Question


class DateTimeLocal(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%dT%H:%M", **kw)


class AssessmentForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ["title", "kind", "instructions", "duration_minutes", "max_attempts", "due_at", "show_answers"]
        widgets = {"due_at": DateTimeLocal(), "instructions": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["due_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        self._style()

    def clean_max_attempts(self):
        v = self.cleaned_data["max_attempts"]
        if v < 1:
            raise forms.ValidationError("At least 1 attempt.")
        return v


class QuestionForm(StyledMixin, forms.ModelForm):
    choice1 = forms.CharField(label="Option 1", required=False, max_length=300)
    choice2 = forms.CharField(label="Option 2", required=False, max_length=300)
    choice3 = forms.CharField(label="Option 3", required=False, max_length=300)
    choice4 = forms.CharField(label="Option 4", required=False, max_length=300)
    correct = forms.ChoiceField(label="Correct option", required=False,
                                choices=[("", "—"), ("1", "Option 1"), ("2", "Option 2"), ("3", "Option 3"), ("4", "Option 4")])
    tf_answer = forms.ChoiceField(label="Correct answer (True / False)", required=False,
                                  choices=[("", "—"), ("true", "True"), ("false", "False")])

    class Meta:
        model = Question
        fields = ["kind", "text", "points", "explanation", "accepted"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3}), "explanation": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        inst = self.instance
        if inst.pk:
            if inst.kind == Question.Kind.MCQ:
                for i, c in enumerate(inst.choices.all()[:4], start=1):
                    self.initial[f"choice{i}"] = c.text
                    if c.is_correct:
                        self.initial["correct"] = str(i)
            elif inst.kind == Question.Kind.TF:
                c = inst.choices.filter(is_correct=True).first()
                self.initial["tf_answer"] = "true" if c and c.text == "True" else "false" if c else ""
        for name in ("text", "explanation", "accepted", "choice1", "choice2", "choice3", "choice4"):
            self.fields[name].widget.attrs["data-ed"] = "1"   # the subject-aware editor attaches its tools to these
        self._style()

    def clean_points(self):
        v = self.cleaned_data["points"]
        if v <= 0:
            raise forms.ValidationError("Points must be more than 0.")
        return v

    def clean(self):
        d = super().clean()
        kind = d.get("kind")
        if kind == Question.Kind.MCQ:
            opts = [d.get(f"choice{i}", "").strip() for i in range(1, 5)]
            if sum(1 for o in opts if o) < 2:
                self.add_error("choice2", "Give at least two options.")
            c = d.get("correct")
            if not c:
                self.add_error("correct", "Select the correct option.")
            elif not opts[int(c) - 1]:
                self.add_error("correct", "The correct option cannot be empty.")
        elif kind == Question.Kind.TF and not d.get("tf_answer"):
            self.add_error("tf_answer", "Select True or False.")
        elif kind == Question.Kind.SHORT and not (d.get("accepted") or "").strip("| "):
            self.add_error("accepted", "Enter at least one accepted answer.")
        return d

    def save_with_choices(self, assessment):
        q = self.save(commit=False)
        q.assessment = assessment
        if q.kind != Question.Kind.SHORT:
            q.accepted = ""
        q.save()
        q.choices.all().delete()
        d = self.cleaned_data
        if q.kind == Question.Kind.MCQ:
            for i in range(1, 5):
                t = d.get(f"choice{i}", "").strip()
                if t:
                    Choice.objects.create(question=q, text=t, position=i, is_correct=(d["correct"] == str(i)))
        elif q.kind == Question.Kind.TF:
            Choice.objects.create(question=q, text="True", position=1, is_correct=d["tf_answer"] == "true")
            Choice.objects.create(question=q, text="False", position=2, is_correct=d["tf_answer"] == "false")
        return q
