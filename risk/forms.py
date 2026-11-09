from django import forms

from .models import EarlyWarningSettings


class SettingsForm(forms.ModelForm):
    class Meta:
        model = EarlyWarningSettings
        fields = ["window_days", "attendance_below", "exam_below", "exam_drop", "quiz_below", "struggling_nuggets", "min_signals"]

    def clean(self):
        d = super().clean()
        for k in ("attendance_below", "exam_below", "quiz_below"):
            if d.get(k) is not None and not 1 <= d[k] <= 100:
                self.add_error(k, "Use a value between 1 and 100.")
        if d.get("window_days") is not None and not 7 <= d["window_days"] <= 365:
            self.add_error("window_days", "Use between 7 and 365 days.")
        if d.get("min_signals") is not None and d["min_signals"] < 1:
            self.add_error("min_signals", "At least 1.")
        return d
