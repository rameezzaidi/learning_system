from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.school_settings, name="settings"),
    path("permissions/", views.permissions, name="permissions"),
    path("audit/", views.audit_log, name="audit"),
]
