from django.urls import path

from . import views

app_name = "nuggets"
urlpatterns = [
    path("nuggets/", views.home, name="home"),
    path("nuggets/refresh/", views.refresh, name="refresh"),
    path("nuggets/manage/", views.manage, name="manage"),
    path("nuggets/new/", views.nugget_form, name="create"),
    path("nuggets/generate/", views.generate, name="generate"),
    path("nuggets/suggest/", views.suggest_view, name="suggest"),
    path("nuggets/insights/", views.insights, name="insights"),
    path("nuggets/auto/", views.auto_exam, name="auto_exam"),
    path("nuggets/<int:pk>/", views.play, name="play"),
    path("nuggets/<int:pk>/tutor/", views.tutor_view, name="tutor"),
    path("nuggets/<int:pk>/approve/", views.approve, name="approve"),
    path("nuggets/<int:pk>/reject/", views.reject, name="reject"),
    path("nuggets/<int:pk>/check/", views.check, name="check"),
    path("nuggets/<int:pk>/edit/", views.nugget_form, name="edit"),
    path("nuggets/<int:pk>/delete/", views.nugget_delete, name="delete"),
    path("nuggets/<int:pk>/stats/", views.stats, name="stats"),
    path("nuggets/<int:pk>/assign/", views.assign, name="assign"),
]
