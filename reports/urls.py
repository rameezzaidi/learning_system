from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("reports/students/", views.students_report, name="students"),
    path("reports/students/csv/", views.students_csv, name="students_csv"),
    path("reports/students/pdf/", views.students_pdf, name="students_pdf"),
]
