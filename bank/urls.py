from django.urls import path

from . import views

app_name = "bank"

urlpatterns = [
    path("bank/", views.index, name="index"),
    path("bank/course/<int:pk>/", views.course, name="course"),
]
