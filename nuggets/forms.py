from django import forms

from .models import Nugget

LETTERS = "ABCD"


def questions_to_text(qs):
    lines = []
    for q in qs or []:
        opts = list(q.get("options", []))[:4]
        opts += [""] * (4 - len(opts))
        lines.append(" | ".join([q.get("q", "")] + opts + [LETTERS[q.get("answer", 0)] if q.get("answer", 0) < 4 else "A", q.get("why", "")]))
    return "\n".join(lines)


def parse_questions(text):
    out, errors = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            errors.append(f"Question line {n}: use  question | A | B | C | D | correct letter | explanation")
            continue
        q, opts, letter = parts[0], parts[1:5], parts[5].upper()[:1]
        why = " | ".join(parts[6:]).strip()
        if letter not in LETTERS or not opts[LETTERS.index(letter)]:
            errors.append(f"Question line {n}: the correct letter must be A, B, C or D and point to a filled option.")
            continue
        shown = [o for o in opts if o]
        if len(shown) < 2:
            errors.append(f"Question line {n}: give at least two options.")
            continue
        out.append({"q": q, "options": shown, "answer": shown.index(opts[LETTERS.index(letter)]), "why": why})
    return out, errors


def parse_cards(text):
    out = []
    for line in text.splitlines():
        a, _, b = line.partition("|")
        if a.strip() and b.strip():
            out.append([a.strip(), b.strip()])
    return out


class NuggetForm(forms.ModelForm):
    cards_text = forms.CharField(label="Flashcards", required=False, widget=forms.Textarea(attrs={"rows": 6, "placeholder": "front | back  (one per line)"}))
    questions_text = forms.CharField(label="Quick check questions", required=False, widget=forms.Textarea(
        attrs={"rows": 7, "placeholder": "2 + 2 = ? | 3 | 4 | 5 | 6 | B | Because 2 + 2 is 4"}),
        help_text="One per line:  question | A | B | C | D | correct letter | explanation")

    class Meta:
        model = Nugget
        fields = ["course", "topic", "title", "explanation", "key_points", "video_url", "minutes", "difficulty", "is_published"]
        widgets = {"explanation": forms.Textarea(attrs={"rows": 6}), "key_points": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *a, courses=None, **kw):
        super().__init__(*a, **kw)
        for name, f in self.fields.items():
            w = f.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            w.attrs["class"] = ("select" if isinstance(w, forms.Select) else "input")
        self.fields["explanation"].help_text = "Use the toolbar for bold, lists and headings. Short paragraphs and one worked example work best."
        self.fields["course"].empty_label = "Choose a course…"
        self.fields["topic"].widget.attrs["placeholder"] = "e.g. Fractions"
        self.fields["title"].widget.attrs["placeholder"] = "e.g. Adding fractions in 5 minutes"
        self.fields["video_url"].widget.attrs["placeholder"] = "https://www.youtube.com/watch?v=…  (optional)"
        self.fields["video_url"].label = "Video link"
        self.fields["is_published"].label = "Visible to students"
        self.fields["minutes"].label = "Minutes"
        if courses is not None:
            self.fields["course"].queryset = courses
        if self.instance.pk:
            self.fields["cards_text"].initial = "\n".join(" | ".join(c) for c in self.instance.cards)
            self.fields["questions_text"].initial = questions_to_text(self.instance.questions)

    def clean_questions_text(self):
        qs, errors = parse_questions(self.cleaned_data.get("questions_text", ""))
        if errors:
            raise forms.ValidationError(errors)
        self._questions = qs
        return self.cleaned_data["questions_text"]

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.cards = parse_cards(self.cleaned_data.get("cards_text", ""))
        obj.questions = getattr(self, "_questions", [])
        if commit:
            obj.save()
        return obj
