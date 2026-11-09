from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("login/verify/", views.verify2fa, name="verify2fa"),
    path("security/", views.security, name="security"),
    path("security/2fa/setup/", views.twofa_setup, name="twofa_setup"),
    path("security/2fa/disable/", views.twofa_disable, name="twofa_disable"),
    path("password/", views.PasswordView.as_view(), name="password"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/toggle/", views.user_toggle, name="user_toggle"),
]
