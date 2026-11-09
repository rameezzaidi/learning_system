from django.urls import path

from . import views

app_name = "fees"

urlpatterns = [
    path("fees/", views.dashboard, name="dashboard"),
    path("fees/generate/", views.generate, name="generate"),
    path("fees/classes/", views.defaults, name="defaults"),
    path("fees/me/", views.my, name="my"),
    path("fees/student/<int:pk>/", views.ledger, name="ledger"),
    path("fees/student/<int:pk>/pay/", views.pay, name="pay"),
    path("fees/student/<int:pk>/entry/", views.entry, name="entry"),
    path("fees/student/<int:pk>/plan/", views.plan, name="plan"),
    path("fees/entry/<int:pk>/void/", views.void, name="void"),
    path("fees/receipt/<int:pk>/", views.receipt, name="receipt"),
]
