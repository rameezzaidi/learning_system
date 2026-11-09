from django.urls import path

from . import views

app_name = "sis"

urlpatterns = [
    path("admissions/", views.admissions, name="admissions"),
    path("admissions/new/", views.admission_new, name="admission_new"),
    path("admissions/<int:pk>/", views.admission, name="admission"),
    path("students/<int:pk>/documents/", views.documents, name="documents"),
    path("documents/<int:pk>/", views.document_file, name="document_file"),
    path("promotion/", views.promotion, name="promotion"),
    path("students/<int:pk>/transfer-certificate/", views.tc_issue, name="tc_issue"),
    path("certificates/<int:pk>/", views.tc, name="tc"),
]
