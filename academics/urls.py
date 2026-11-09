from django.urls import path

from . import builder, help as helpdesk, views

app_name = "academics"

urlpatterns = [
    # classes
    path("classes/", views.class_list, name="class_list"),
    path("classes/new/", views.class_form, name="class_create"),
    path("classes/<int:pk>/", views.class_detail, name="class_detail"),
    path("classes/<int:pk>/edit/", views.class_form, name="class_edit"),
    path("classes/<int:pk>/delete/", views.class_delete, name="class_delete"),
    path("classes/<int:pk>/enroll/", views.enroll, name="enroll"),
    path("classes/<int:pk>/unenroll/<int:student_pk>/", views.unenroll, name="unenroll"),
    # subjects
    path("subjects/", views.subject_list, name="subject_list"),
    path("subjects/<int:pk>/delete/", views.subject_delete, name="subject_delete"),
    # courses
    path("classes/<int:class_pk>/courses/new/", views.course_form, name="course_create"),
    path("courses/<int:pk>/edit/", views.course_form, name="course_edit"),
    path("courses/<int:pk>/delete/", views.course_delete, name="course_delete"),
    path("courses/", views.my_courses, name="my_courses"),
    path("courses/<int:pk>/", views.course_detail, name="course_detail"),
    # lessons
    path("courses/<int:course_pk>/lessons/new/", views.lesson_form, name="lesson_create"),
    path("lessons/<int:pk>/", views.lesson_view, name="lesson_view"),
    path("lessons/<int:pk>/edit/", views.lesson_form, name="lesson_edit"),
    path("lessons/<int:pk>/delete/", views.lesson_delete, name="lesson_delete"),
    path("lessons/<int:pk>/done/", views.item_done, name="item_done"),
    # modules & ordering (teacher)
    path("courses/<int:course_pk>/modules/new/", builder.module_form, name="module_create"),
    path("modules/<int:pk>/edit/", builder.module_form, name="module_edit"),
    path("modules/<int:pk>/delete/", builder.module_delete, name="module_delete"),
    path("modules/<int:pk>/toggle/", builder.module_toggle, name="module_toggle"),
    path("modules/<int:pk>/move/<str:direction>/", builder.module_move, name="module_move"),
    path("lessons/<int:pk>/toggle/", builder.lesson_toggle, name="lesson_toggle"),
    path("lessons/<int:pk>/move/<str:direction>/", builder.lesson_move, name="lesson_move"),
    # help desk
    path("courses/<int:course_pk>/help/", helpdesk.help_ask, name="help_ask"),
    path("help/", helpdesk.help_list, name="help_list"),
    path("help/<int:pk>/", helpdesk.help_thread, name="help_thread"),
    # parent
    path("children/<int:student_pk>/", views.child_progress, name="child_progress"),
]
