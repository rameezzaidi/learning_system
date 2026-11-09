from django import forms

from .models import SchoolSettings


class SchoolSettingsForm(forms.ModelForm):
    class Meta:
        model = SchoolSettings
        fields = [
            "school_name", "tagline", "theme", "use_custom_colors", "custom_primary", "custom_accent",
            "font_style", "radius", "sidebar_style", "allow_user_theme", "auto_approve_nuggets", "currency",
        ]
        widgets = {
            "school_name": forms.TextInput(attrs={"class": "input"}),
            "tagline": forms.TextInput(attrs={"class": "input"}),
            "theme": forms.RadioSelect(),
            "custom_primary": forms.TextInput(attrs={"type": "color", "class": "color-input"}),
            "custom_accent": forms.TextInput(attrs={"type": "color", "class": "color-input"}),
            "font_style": forms.RadioSelect(),
            "radius": forms.RadioSelect(),
            "sidebar_style": forms.RadioSelect(),
        }

    def clean_currency(self):
        return (self.cleaned_data.get("currency") or "").strip() or "Rs"
