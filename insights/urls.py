from django.urls import path

from . import views

app_name = "insights"

urlpatterns = [
    path("insights/profile/<int:pk>/", views.dna, name="dna"),
    path("insights/lesson-plan/", views.lesson_plan, name="lesson_plan"),
    path("insights/executive/", views.executive, name="executive"),
]
