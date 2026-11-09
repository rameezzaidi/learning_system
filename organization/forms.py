from django import forms

from accounts.forms import StyledMixin
from accounts.models import User

from .models import Campus, Region, StudentProfile, SyncSettings


class RegionForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Region
        fields = ["name", "code", "is_active"]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()


class CampusForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Campus
        fields = ["region", "name", "code", "is_active"]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["region"].queryset = Region.objects.filter(is_active=True) | Region.objects.filter(
            pk=getattr(self.instance, "region_id", None)
        )
        self._style()


class StudentForm(StyledMixin, forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(max_length=150, help_text="Used to sign in. Admission number works well.")
    admission_no = forms.CharField(max_length=40, required=False)
    campus = forms.ModelChoiceField(queryset=Campus.objects.none(), required=False, empty_label="— No campus —")
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=30, required=False)
    password = forms.CharField(widget=forms.PasswordInput, required=False)

    def __init__(self, *args, user=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        qs = Campus.objects.filter(is_active=True).select_related("region")
        if actor is not None and actor.is_management:
            from core.scope import campus_ids
            ids = campus_ids(actor)
            if ids is not None:
                qs = qs.filter(pk__in=ids)
                self.fields["campus"].required = True
                self.fields["campus"].empty_label = None
        self.fields["campus"].queryset = qs
        self.fields["campus"].label_from_instance = lambda c: f"{c.region.name} › {c.name}"
        if user:
            self.fields["password"].label = "New password (leave blank to keep)"
            profile = StudentProfile.objects.filter(user=user).first()
            if not self.is_bound:
                self.initial = {
                    "first_name": user.first_name, "last_name": user.last_name, "username": user.username,
                    "email": user.email, "phone": user.phone,
                    "admission_no": profile.admission_no if profile else "",
                    "campus": profile.campus_id if profile else None,
                }
        else:
            self.fields["password"].required = True
        self._style()

    def clean_username(self):
        name = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username=name)
        if self.user:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return name

    def save(self):
        d = self.cleaned_data
        u = self.user or User(role=User.Role.STUDENT)
        u.username, u.first_name, u.last_name = d["username"], d["first_name"], d["last_name"]
        u.email, u.phone = d["email"], d["phone"]
        if d["password"]:
            u.set_password(d["password"])
        u.save()
        profile, _ = StudentProfile.objects.get_or_create(user=u, defaults={"source": "manual"})
        profile.campus = d["campus"]
        profile.admission_no = d["admission_no"]
        profile.save()
        return u


class SyncSettingsForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = SyncSettings
        fields = ["enabled", "interval_minutes", "deactivate_missing", "sql_regions", "sql_campuses", "sql_students"]
        widgets = {k: forms.Textarea(attrs={"rows": 5, "spellcheck": "false", "style": "font-family:monospace"})
                   for k in ("sql_regions", "sql_campuses", "sql_students")}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()
