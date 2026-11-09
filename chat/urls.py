from django.urls import path

from . import views

app_name = "chat"
urlpatterns = [
    path("chat/", views.home, name="home"),
    path("chat/new/", views.new, name="new"),
    path("chat/people/", views.people, name="people"),
    path("chat/list.json", views.conversations_json, name="list_json"),
    path("chat/with/<int:user_pk>/", views.start, name="start"),
    path("chat/<int:pk>/", views.home, name="thread"),
    path("chat/<int:pk>/messages/", views.messages_json, name="messages"),
    path("chat/<int:pk>/send/", views.send, name="send"),
]
