from django.urls import path

from . import views

app_name = "assessments"

urlpatterns = [
    path("assessments/", views.assessment_list, name="list"),
    path("courses/<int:course_pk>/assessments/new/", views.assessment_form, name="create"),
    path("assessments/<int:pk>/", views.assessment_detail, name="detail"),
    path("assessments/<int:pk>/edit/", views.assessment_form, name="edit"),
    path("assessments/<int:pk>/toggle/", views.assessment_toggle, name="toggle"),
    path("assessments/<int:pk>/delete/", views.assessment_delete, name="delete"),
    path("assessments/<int:assessment_pk>/questions/new/", views.question_form, name="question_create"),
    path("questions/<int:pk>/edit/", views.question_form, name="question_edit"),
    path("questions/<int:pk>/delete/", views.question_delete, name="question_delete"),
    path("assessments/<int:pk>/results/", views.results, name="results"),
    path("attempts/<int:pk>/review/", views.attempt_review, name="review"),
    path("assessments/<int:pk>/start/", views.start, name="start"),
    path("attempts/<int:pk>/take/", views.take, name="take"),
    path("attempts/<int:pk>/", views.result, name="result"),
    path("progress/", views.my_progress, name="progress"),
    path("gradebook/", views.gradebook_index, name="gradebook_index"),
    path("gradebook/<int:course_pk>/", views.gradebook, name="gradebook"),
    path("gradebook/<int:course_pk>/csv/", views.gradebook_csv, name="gradebook_csv"),
]
