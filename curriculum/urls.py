from django.urls import path

from . import views

app_name = "curriculum"

urlpatterns = [
    path("curriculum/", views.index, name="index"),
    path("curriculum/coverage/", views.monitor, name="monitor"),
    path("curriculum/course/<int:pk>/", views.outline, name="outline"),
    path("curriculum/course/<int:pk>/add/", views.topics_add, name="topics_add"),
    path("curriculum/course/<int:pk>/copy/", views.topics_copy, name="topics_copy"),
    path("curriculum/course/<int:pk>/handover/", views.handover_new, name="handover_new"),
    path("curriculum/topic/<int:pk>/toggle/", views.topic_toggle, name="topic_toggle"),
    path("curriculum/topic/<int:pk>/delete/", views.topic_delete, name="topic_delete"),
    path("curriculum/handovers/", views.handover_list, name="handover_list"),
    path("curriculum/handovers/<int:pk>/", views.handover_detail, name="handover_detail"),
    path("curriculum/handovers/<int:pk>/ack/", views.handover_ack, name="handover_ack"),
    path("curriculum/handovers/<int:pk>/close/", views.handover_close, name="handover_close"),
]
