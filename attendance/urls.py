from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("attendance/", views.index, name="index"),
    path("attendance/class/<int:pk>/", views.mark, name="mark"),
    path("attendance/me/", views.my, name="my"),
    path("attendance/student/<int:pk>/", views.student, name="student"),
    path("attendance/student/<int:pk>/leave/", views.leave_request, name="leave_request"),
    path("attendance/leaves/", views.leaves, name="leaves"),
    path("attendance/leaves/<int:pk>/decide/", views.leave_decide, name="leave_decide"),
    path("attendance/report/", views.report, name="report"),
    path("attendance/staff/", views.staff, name="staff"),
]
