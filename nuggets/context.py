def badge(request):
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated or not getattr(u, "is_student", False):
        return {}
    try:
        from django.utils import timezone

        from .models import StudentNugget
        qs = StudentNugget.objects.filter(student=u, nugget__is_published=True, nugget__review="approved")
        todo = qs.filter(status="assigned").count()
        due = qs.filter(status="done", next_review__lte=timezone.localdate()).count()
        return {"nugget_badge": todo + due}
    except Exception:
        return {}
