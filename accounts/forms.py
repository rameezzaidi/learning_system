from django import forms
from django.contrib.auth.forms import AuthenticationForm

from core.themes import THEME_CHOICES

from .models import User


class StyledMixin:
    def _style(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue
            cls = "select" if isinstance(w, forms.Select) else "input"
            if isinstance(w, forms.SelectMultiple):
                cls = "select multi"
            w.attrs["class"] = (w.attrs.get("class", "") + " " + cls).strip()


class LoginForm(StyledMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"placeholder": "Username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"placeholder": "Password"})
        self._style()


class UserCreateForm(StyledMixin, forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "email", "phone", "role", "region", "campus", "children", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["children"].queryset = User.objects.filter(role=User.Role.STUDENT)
        self.fields["children"].required = False
        self.fields["children"].label = "Linked students (for parents)"
        self.fields["first_name"].required = True
        self._style()

    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"):
            self.add_error("password2", "Passwords do not match.")
        if data.get("role") != User.Role.PARENT:
            data["children"] = []
        role = data.get("role")
        if role == User.Role.PRINCIPAL and not data.get("campus"):
            self.add_error("campus", "A Campus Principal must be tied to a campus.")
        if role == User.Role.REGIONAL and not data.get("region"):
            self.add_error("region", "A Regional Director must be tied to a region.")
        if role == User.Role.PRINCIPAL:
            data["region"] = None
        elif role == User.Role.REGIONAL:
            data["campus"] = None
        elif role != User.Role.TEACHER:
            data["region"] = data["campus"] = None
        elif data.get("campus"):
            data["region"] = None
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self.save_m2m()
        return user


class UserEditForm(StyledMixin, forms.ModelForm):
    new_password = forms.CharField(
        label="New password (leave blank to keep)", required=False, widget=forms.PasswordInput
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "email", "phone", "role", "region", "campus", "children", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["children"].queryset = User.objects.filter(role=User.Role.STUDENT)
        self.fields["children"].required = False
        self.fields["children"].label = "Linked students (for parents)"
        self._style()

    def clean(self):
        data = super().clean()
        if data.get("role") != User.Role.PARENT:
            data["children"] = []
        role = data.get("role")
        if role == User.Role.PRINCIPAL and not data.get("campus"):
            self.add_error("campus", "A Campus Principal must be tied to a campus.")
        if role == User.Role.REGIONAL and not data.get("region"):
            self.add_error("region", "A Regional Director must be tied to a region.")
        if role == User.Role.PRINCIPAL:
            data["region"] = None
        elif role == User.Role.REGIONAL:
            data["campus"] = None
        elif role != User.Role.TEACHER:
            data["region"] = data["campus"] = None
        elif data.get("campus"):
            data["region"] = None
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        pw = self.cleaned_data.get("new_password")
        if pw:
            user.set_password(pw)
        if commit:
            user.save()
            self.save_m2m()
        return user


class ProfileForm(StyledMixin, forms.ModelForm):
    theme = forms.ChoiceField(
        required=False, label="My theme", choices=[("", "Use school default")] + THEME_CHOICES
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "about", "avatar", "theme"]

    def __init__(self, *args, allow_theme=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not allow_theme:
            del self.fields["theme"]
        self.fields["about"].widget = forms.Textarea(attrs={"rows": 2, "maxlength": 240, "placeholder": "A line about you (optional)"})
        self.fields["avatar"].widget = forms.FileInput(attrs={"accept": "image/*"})
        self.fields["avatar"].label = "Profile photo"
        self._style()

    def clean_avatar(self):
        f = self.cleaned_data.get("avatar")
        if f and hasattr(f, "size") and f.size > 3 * 1024 * 1024:
            raise forms.ValidationError("Photo must be under 3 MB.")
        return f
