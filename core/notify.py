"""One place to tell people things: in-app bell + optional email. Never raises."""
import logging

from django.conf import settings
from django.core.mail import send_mail

from .models import Notification

log = logging.getLogger(__name__)


def notify(user, title, body="", url="", kind=""):
    try:
        n = Notification.objects.create(user=user, title=title[:160], body=body[:300], url=url[:200], kind=kind[:20])
        if getattr(settings, "EMAIL_NOTIFICATIONS", False) and user.email:
            send_mail(f"[{getattr(settings, 'SITE_NAME', 'EduPulse')}] {title}"[:200], f"{body}\n\n{url}".strip(),
                      settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)
        return n
    except Exception:  # a notification must never break the real action
        log.exception("notify failed")
        return None


def notify_family(student, title, body="", student_url="", parent_url="", kind=""):
    """The student and every linked parent."""
    notify(student, title, body, student_url, kind)
    for p in student.parents.filter(is_active=True):
        notify(p, f"{student.display_name}: {title}", body, parent_url or student_url, kind)
