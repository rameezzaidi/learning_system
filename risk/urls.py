from django.urls import path

from . import views

app_name = "risk"

urlpatterns = [
    path("risk/", views.index, name="index"),
    path("risk/settings/", views.settings_view, name="settings"),
    path("risk/scan/", views.run_scan, name="scan"),
    path("risk/<int:pk>/", views.detail, name="detail"),
]
