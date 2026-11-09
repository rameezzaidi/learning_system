from django.urls import path

from . import views

app_name = "timetable"

urlpatterns = [
    path("timetable/", views.index, name="index"),
    path("timetable/mine/", views.mine, name="mine"),
    path("timetable/class/<int:pk>/", views.class_view, name="class"),
    path("timetable/class/<int:pk>/edit/", views.edit, name="edit"),
    path("timetable/periods/", views.periods, name="periods"),
    path("timetable/substitutions/", views.substitutions, name="substitutions"),
    path("calendar/", views.calendar_view, name="calendar"),
]
