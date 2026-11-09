from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"
        PARENT = "parent", "Parent"
        HEAD_OFFICE = "head_office", "Head Office Admin"
        REGIONAL = "regional_director", "Regional Director"
        PRINCIPAL = "principal", "Campus Principal"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    phone = models.CharField(max_length=30, blank=True)
    avatar = models.ImageField(upload_to="avatars/%Y/", blank=True)
    about = models.CharField("About me", max_length=240, blank=True)
    # Personal theme (blank = follow school theme). Only used if school allows it.
    theme = models.CharField(max_length=30, blank=True)
    # A parent can be linked to several students (and a student to several parents).
    children = models.ManyToManyField(
        "self", symmetrical=False, related_name="parents", blank=True,
        limit_choices_to={"role": "student"},
    )

    # Management scope: a Regional Director sees one region, a Principal one campus.
    # Head Office / Super Admin leave both empty and see every campus.
    region = models.ForeignKey("organization.Region", null=True, blank=True, on_delete=models.SET_NULL, related_name="directors")
    campus = models.ForeignKey("organization.Campus", null=True, blank=True, on_delete=models.SET_NULL, related_name="staff")

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.SUPER_ADMIN
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def is_super_admin(self):
        return self.role == self.Role.SUPER_ADMIN

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_parent(self):
        return self.role == self.Role.PARENT

    @property
    def is_management(self):
        return self.role in (self.Role.HEAD_OFFICE, self.Role.REGIONAL, self.Role.PRINCIPAL)

    @property
    def is_staff_role(self):
        return self.is_super_admin or self.is_teacher or self.is_management


class RolePermission(models.Model):
    """Super Admin override of one default permission for one role (see accounts/rbac.py)."""

    role = models.CharField(max_length=20)
    code = models.CharField(max_length=60)
    allowed = models.BooleanField()

    class Meta:
        unique_together = ("role", "code")


class TwoFactor(models.Model):
    """Authenticator-app second step. Enabled only after the user proves they can generate a code."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="twofactor")
    secret = models.CharField(max_length=64)
    enabled = models.BooleanField(default=False)
    backup_hashes = models.JSONField(default=list)
    confirmed_at = models.DateTimeField(null=True, blank=True)


class UserSession(models.Model):
    """Where an account is signed in, so the user can see and end sessions."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_sessions")
    session_key = models.CharField(max_length=64, unique=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
