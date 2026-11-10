from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from core import cron, notif_views


def healthz(request):
    from django.db import connection
    connection.ensure_connection()
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("cron/daily/", cron.daily, name="cron_daily"),
    path("cron/setup/", cron.setup, name="cron_setup"),
    path("notifications/", notif_views.notifications, name="core_notifications"),
    path("notifications/read-all/", notif_views.notifications_read_all, name="core_notifications_read"),
    path("notifications/<int:pk>/", notif_views.notification_open, name="core_notification_open"),
    path("django-admin/", admin.site.urls),
    path("settings/", include("core.urls")),
    path("", include("reports.urls")),
    path("", include("organization.urls")),
    path("", include("academics.urls")),
    path("", include("assessments.urls")),
    path("", include("exams.urls")),
    path("", include("chat.urls")),
    path("", include("nuggets.urls")),
    path("", include("curriculum.urls")),
    path("", include("fees.urls")),
    path("", include("attendance.urls")),
    path("", include("risk.urls")),
    path("", include("timetable.urls")),
    path("", include("sis.urls")),
    path("", include("bank.urls")),
    path("", include("insights.urls")),
    path("", include("campusops.urls")),
    path("", include("accounts.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
