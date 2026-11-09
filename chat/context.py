from django.db import OperationalError, ProgrammingError


def unread(request):
    u = getattr(request, "user", None)
    if u is None or not u.is_authenticated:
        return {}
    try:
        from .models import Message, Participant
        n = 0
        for p in Participant.objects.filter(user=u).only("conversation_id", "last_read_at"):
            n += Message.objects.filter(conversation_id=p.conversation_id, created_at__gt=p.last_read_at).exclude(sender=u).count()
        return {"chat_unread": n}
    except (OperationalError, ProgrammingError):
        return {}
