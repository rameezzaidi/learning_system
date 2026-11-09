from django.db import OperationalError, ProgrammingError

from .models import SchoolSettings
from .themes import DEFAULT_THEME, THEMES


def contrast_for(hex_color):
    """Return a readable text colour (white/near-black) for a hex background."""
    h = (hex_color or "#2563eb").lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#ffffff"
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#0b1220" if luminance > 0.62 else "#ffffff"


def school(request):
    try:
        s = SchoolSettings.load()
    except (OperationalError, ProgrammingError):  # before first migrate
        s = SchoolSettings()
    user = getattr(request, "user", None)
    theme = s.theme if s.theme in THEMES else DEFAULT_THEME
    if s.allow_user_theme and user is not None and user.is_authenticated and user.theme in THEMES:
        theme = user.theme
    use_custom = s.use_custom_colors and theme == s.theme
    from django.conf import settings

    from accounts.rbac import has_perm
    perms_audit = bool(user is not None and user.is_authenticated and has_perm(user, "audit.view"))

    perms_monitor = bool(user is not None and user.is_authenticated and has_perm(user, "curriculum.monitor"))

    perms_fees = bool(user is not None and user.is_authenticated and has_perm(user, "fees.view"))

    authed = user is not None and user.is_authenticated
    perms_att_mark = bool(authed and has_perm(user, "attendance.mark"))
    perms_att_view = bool(authed and has_perm(user, "attendance.view"))
    perms_leave = bool(authed and has_perm(user, "attendance.leave_decide") and (user.is_super_admin or user.is_teacher or user.is_management))
    perms_risk = bool(authed and has_perm(user, "risk.view") and (user.is_super_admin or user.is_teacher or user.is_management))
    risk_badge = 0
    if perms_risk:
        try:
            from risk.services import open_count
            risk_badge = open_count(user)
        except Exception:
            risk_badge = 0
    from timetable.services import can_manage as _tt_manage
    perms_tt_manage = bool(authed and (user.is_super_admin or user.is_management) and _tt_manage(user))
    perms_sis = bool(authed and has_perm(user, "sis.view") and (user.is_super_admin or user.is_management))
    perms_sis_manage = bool(authed and has_perm(user, "sis.manage") and (user.is_super_admin or user.is_management))
    perms_bank = bool(authed and has_perm(user, "bank.manage") and (user.is_super_admin or user.is_teacher or user.is_management))
    perms_bi = bool(authed and has_perm(user, "bi.view") and (user.is_super_admin or user.is_management))
    perms_library = bool(authed and has_perm(user, "library.manage") and (user.is_super_admin or user.is_management))
    perms_transport = bool(authed and (has_perm(user, "transport.view") or has_perm(user, "transport.manage")) and (user.is_super_admin or user.is_management))
    return {"perms_bank": perms_bank, "perms_bi": perms_bi, "perms_library": perms_library, "perms_transport": perms_transport, "perms_sis": perms_sis, "perms_sis_manage": perms_sis_manage, "perms_tt_manage": perms_tt_manage, "perms_att_mark": perms_att_mark, "perms_att_view": perms_att_view, "perms_leave": perms_leave,
        "perms_risk": perms_risk, "risk_badge": risk_badge, "perms_fees": perms_fees, "perms_audit": perms_audit, "perms_monitor": perms_monitor,
        "debug": settings.DEBUG,
        "school": s,
        "THEMES": THEMES,
        "active_theme": theme,
        "use_custom": use_custom,
        "custom_contrast": contrast_for(s.custom_primary),
    }


def bell(request):
    """Unread count + the latest few notifications for the topbar bell."""
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated:
        return {}
    try:
        from .models import Notification
        qs = Notification.objects.filter(user=u)
        return {"bell_unread": qs.filter(is_read=False).count(), "bell_items": list(qs[:6])}
    except Exception:
        return {}
