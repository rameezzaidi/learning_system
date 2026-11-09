from django.urls import path

from . import views

app_name = "campusops"

urlpatterns = [
    path("library/", views.library, name="library"),
    path("transport/", views.transport, name="transport"),
]
