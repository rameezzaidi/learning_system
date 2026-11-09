from django.urls import path

from . import family, views

app_name = "organization"

urlpatterns = [
    path("organization/", views.overview, name="overview"),
    path("organization/regions/new/", views.region_form, name="region_create"),
    path("organization/regions/<int:pk>/edit/", views.region_form, name="region_edit"),
    path("organization/regions/<int:pk>/delete/", views.region_delete, name="region_delete"),
    path("organization/campuses/new/", views.campus_form, name="campus_create"),
    path("organization/campuses/<int:pk>/edit/", views.campus_form, name="campus_edit"),
    path("organization/campuses/<int:pk>/delete/", views.campus_delete, name="campus_delete"),
    path("organization/compare/", views.compare, name="compare"),
    path("students/export/", views.student_export, name="student_export"),
    path("students/", views.student_list, name="student_list"),
    path("students/new/", views.student_create, name="student_create"),
    path("students/<int:pk>/profile/", views.student_profile, name="student_profile"),
    path("students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("family/", family.family_home, name="family_home"),
    path("family/<int:pk>/", family.child_overview, name="family"),
    path("sync/", views.sync_page, name="sync"),
    path("sync/test/", views.sync_test, name="sync_test"),
    path("sync/run/", views.sync_now, name="sync_now"),
]
