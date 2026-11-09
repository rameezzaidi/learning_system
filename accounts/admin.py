from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class EduUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (("EduPulse", {"fields": ("role", "phone", "theme", "children")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("EduPulse", {"fields": ("role",)}),)
