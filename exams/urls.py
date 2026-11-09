from django.urls import path

from . import views

app_name = "exams"

urlpatterns = [
    path("exams/", views.exam_list, name="list"),
    path("exams/new/", views.exam_form, name="create"),
    path("exams/<int:pk>/", views.exam_detail, name="detail"),
    path("exams/<int:pk>/edit/", views.exam_form, name="edit"),
    path("exams/<int:pk>/delete/", views.exam_delete, name="delete"),
    path("exams/<int:pk>/toggle/<str:what>/", views.exam_toggle, name="toggle"),
    path("exams/<int:exam_pk>/papers/new/", views.paper_form, name="paper_create"),
    path("papers/<int:pk>/edit/", views.paper_form, name="paper_edit"),
    path("papers/<int:pk>/delete/", views.paper_delete, name="paper_delete"),
    path("papers/<int:paper_pk>/marks/", views.marks_entry, name="marks"),
    path("papers/<int:paper_pk>/import/", views.marks_import, name="marks_import"),
    path("exams/<int:pk>/students/", views.student_list, name="students"),
    path("exams/<int:exam_pk>/students/<int:student_pk>/marks/", views.student_marks, name="student_marks"),
    path("exams/<int:pk>/results/", views.result_sheet, name="sheet"),
    path("exams/<int:pk>/analysis/", views.analysis, name="analysis"),
    path("exams/<int:pk>/ai/", views.ai_generate, name="ai"),
    path("exams/<int:exam_pk>/card/<int:student_pk>/", views.report_card, name="report_card"),
    path("exams/<int:exam_pk>/card/<int:student_pk>/pdf/", views.report_card_pdf_view, name="report_card_pdf"),
    path("results/", views.my_results, name="my_results"),
    path("children/<int:student_pk>/results/", views.my_results, name="child_results"),
    path("grade-scale/", views.gradescale, name="gradescale"),
    path("grade-scale/<int:pk>/edit/", views.gradeband_edit, name="gradeband_edit"),
    path("grade-scale/<int:pk>/delete/", views.gradeband_delete, name="gradeband_delete"),
]
