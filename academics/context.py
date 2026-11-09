from .models import HelpRequest


def help_badge(request):
    """Number shown next to Help in the sidebar: open questions for teachers, new answers for students."""
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated:
        return {}
    try:
        if u.is_super_admin:
            n = HelpRequest.objects.filter(status="open").count()
        elif u.is_teacher:
            n = HelpRequest.objects.filter(course__teacher=u, status="open").count()
        elif u.is_student:
            n = HelpRequest.objects.filter(student=u, status="answered").count()
        else:
            n = 0
    except Exception:
        n = 0
    return {"help_badge": n}
