"""Write audit entries. Never raises: auditing must not break the request."""
import logging

log = logging.getLogger("edupulse.audit")


def _ip(request):
    if not request:
        return None
    return (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR") or None)


def record(request, action, target="", detail="", user=None, campus=None):
    try:
        from .models import AuditLog
        u = user or (getattr(request, "user", None) if request else None)
        u = u if getattr(u, "is_authenticated", False) else None
        AuditLog.objects.create(user=u, username=(u.username if u else ""), action=action[:40], target=str(target)[:160],
                                detail=str(detail)[:400], ip=_ip(request), campus=campus)
    except Exception:  # pragma: no cover
        log.exception("audit write failed")
