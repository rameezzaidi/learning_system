from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed

        from . import audit

        def _in(sender, request, user, **kw):
            audit.record(request, "login", user.username, user=user)

        def _out(sender, request, user, **kw):
            if user:
                audit.record(request, "logout", user.username, user=user)

        def _fail(sender, credentials, request=None, **kw):
            audit.record(request, "login.failed", str((credentials or {}).get("username", ""))[:80])

        def _track(sender, request, user, **kw):
            try:
                from accounts.models import UserSession
                if request is None:
                    return
                if not request.session.session_key:
                    request.session.save()
                UserSession.objects.update_or_create(
                    session_key=request.session.session_key,
                    defaults={"user": user, "ip": audit._ip(request) or None, "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200]})
            except Exception:  # pragma: no cover
                pass

        user_logged_in.connect(_track, dispatch_uid="track_session")
        user_logged_in.connect(_in, dispatch_uid="audit_in")
        user_logged_out.connect(_out, dispatch_uid="audit_out")
        user_login_failed.connect(_fail, dispatch_uid="audit_fail")
