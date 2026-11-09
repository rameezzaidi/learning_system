import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User

from .models import Conversation, Message, Participant
from .permissions import allowed_users, can_chat

MAX_FILE = 8 * 1024 * 1024
BLOCKED_EXT = {".exe", ".bat", ".cmd", ".js", ".msi", ".sh", ".ps1", ".vbs", ".com", ".scr", ".html", ".htm", ".svg", ".php"}


def _me_in(conv_id, user):
    conv = get_object_or_404(Conversation, pk=conv_id)
    part = Participant.objects.filter(conversation=conv, user=user).first()
    if not part:
        raise Http404
    return conv, part


def _msg_json(m, me):
    return {
        "id": m.id, "mine": m.sender_id == me.id, "sender": m.sender.display_name, "sender_id": m.sender_id,
        "avatar": m.sender.avatar.url if m.sender.avatar else "", "initials": "".join(x[0] for x in (m.sender.get_full_name() or m.sender.username).split()[:2]).upper(),
        "body": m.body, "file": m.attachment.url if m.attachment else "", "file_name": m.attachment_name, "is_image": m.is_image,
        "at": timezone.localtime(m.created_at).strftime("%H:%M"), "day": timezone.localtime(m.created_at).strftime("%d %b %Y"),
        "ts": m.created_at.isoformat(),
    }


def _conv_rows(me):
    rows = []
    parts = (Participant.objects.filter(user=me).select_related("conversation")
             .prefetch_related("conversation__participants__user").order_by("-conversation__updated_at"))
    for p in parts:
        c = p.conversation
        last = c.messages.select_related("sender").order_by("-created_at", "-id").first()
        unread = c.messages.filter(created_at__gt=p.last_read_at).exclude(sender=me).count()
        other = c.other_user(me)
        rows.append({"conv": c, "name": c.name_for(me), "other": other, "last": last, "unread": unread,
                     "members": c.participants.count() if c.is_group else 0})
    return rows


@login_required
def home(request, pk=None):
    rows = _conv_rows(request.user)
    active = None
    if pk:
        conv, part = _me_in(pk, request.user)
        active = next((r for r in rows if r["conv"].pk == conv.pk), None)
    msgs = []
    seen_upto = None
    if active:
        msgs = list(active["conv"].messages.select_related("sender").order_by("created_at", "id")[:300])
        Participant.objects.filter(conversation=active["conv"], user=request.user).update(last_read_at=timezone.now())
        active["unread"] = 0
        if not active["conv"].is_group and active["other"]:
            seen_upto = Participant.objects.filter(conversation=active["conv"], user=active["other"]).values_list("last_read_at", flat=True).first()
    return render(request, "chat/home.html", {
        "rows": rows, "active": active, "msgs": msgs, "msgs_json": [_msg_json(m, request.user) for m in msgs],
        "show_profile": bool(active and not active["conv"].is_group and active["other"] and active["other"].is_student and (request.user.is_super_admin or request.user.is_teacher)),
        "members_n": active["conv"].participants.count() if active else 0, "page": "chat", "seen_upto": seen_upto,
        "members": [p.user for p in active["conv"].participants.select_related("user")] if active and active["conv"].is_group else [],
    })


@login_required
def conversations_json(request):
    out = []
    for r in _conv_rows(request.user):
        last = r["last"]
        out.append({"id": r["conv"].pk, "unread": r["unread"], "preview": (("You: " if last and last.sender_id == request.user.id else "") + (last.body[:60] if last and last.body else ("📎 Attachment" if last else ""))),
                    "time": timezone.localtime(last.created_at).strftime("%H:%M") if last else "", "ts": last.created_at.isoformat() if last else ""})
    return JsonResponse({"conversations": out})


@login_required
def messages_json(request, pk):
    conv, part = _me_in(pk, request.user)
    after = int(request.GET.get("after") or 0)
    qs = conv.messages.select_related("sender").filter(id__gt=after).order_by("created_at", "id")
    items = [_msg_json(m, request.user) for m in qs[:100]]
    Participant.objects.filter(pk=part.pk).update(last_read_at=timezone.now())
    seen = None
    if not conv.is_group:
        o = conv.other_user(request.user)
        if o:
            seen = Participant.objects.filter(conversation=conv, user=o).values_list("last_read_at", flat=True).first()
    return JsonResponse({"messages": items, "seen": seen.isoformat() if seen else ""})


@login_required
@require_POST
def send(request, pk):
    conv, part = _me_in(pk, request.user)
    body = (request.POST.get("body") or "").strip()[:4000]
    f = request.FILES.get("file")
    if not body and not f:
        return JsonResponse({"error": "Type a message or attach a file."}, status=400)
    if not conv.is_group:
        o = conv.other_user(request.user)
        if o and not can_chat(request.user, o):
            return JsonResponse({"error": "You can no longer message this person."}, status=403)
    if f:
        import os
        ext = os.path.splitext(f.name)[1].lower()
        if f.size > MAX_FILE:
            return JsonResponse({"error": "File must be under 8 MB."}, status=400)
        if ext in BLOCKED_EXT:
            return JsonResponse({"error": "This file type is not allowed."}, status=400)
    with transaction.atomic():
        m = Message.objects.create(conversation=conv, sender=request.user, body=body, attachment=f or "")
        Conversation.objects.filter(pk=conv.pk).update(updated_at=m.created_at)
        Participant.objects.filter(pk=part.pk).update(last_read_at=m.created_at)
    return JsonResponse({"message": _msg_json(m, request.user)})


@login_required
def people(request):
    q = (request.GET.get("q") or "").strip()
    qs = allowed_users(request.user)
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q))
    out = [{"id": u.pk, "name": u.display_name, "role": u.get_role_display(), "avatar": u.avatar.url if u.avatar else "",
            "initials": "".join(x[0] for x in u.display_name.split()[:2]).upper()} for u in qs.order_by("first_name", "username")[:30]]
    return JsonResponse({"people": out})


@login_required
@require_POST
def new(request):
    ids = [int(x) for x in request.POST.getlist("users") if x.isdigit()]
    title = (request.POST.get("title") or "").strip()[:80]
    allowed = set(allowed_users(request.user).filter(pk__in=ids).values_list("pk", flat=True))
    ids = [i for i in ids if i in allowed]
    if not ids:
        return JsonResponse({"error": "Pick at least one person you are allowed to message."}, status=400)
    if len(ids) == 1 and not title:
        other = ids[0]
        key = Conversation.key_for(request.user.pk, other)
        conv = Conversation.objects.filter(direct_key=key).first()
        if not conv:
            conv = Conversation.objects.create(direct_key=key, created_by=request.user)
            Participant.objects.bulk_create([Participant(conversation=conv, user_id=request.user.pk), Participant(conversation=conv, user_id=other)])
    else:
        conv = Conversation.objects.create(is_group=True, title=title or "New group", created_by=request.user)
        Participant.objects.bulk_create([Participant(conversation=conv, user_id=i) for i in set(ids + [request.user.pk])])
    return JsonResponse({"url": f"/chat/{conv.pk}/"})


@login_required
def start(request, user_pk):
    """Open (or create) a direct chat from a profile page."""
    other = get_object_or_404(User, pk=user_pk)
    if not can_chat(request.user, other):
        raise PermissionDenied
    key = Conversation.key_for(request.user.pk, other.pk)
    conv = Conversation.objects.filter(direct_key=key).first()
    if not conv:
        conv = Conversation.objects.create(direct_key=key, created_by=request.user)
        Participant.objects.bulk_create([Participant(conversation=conv, user=request.user), Participant(conversation=conv, user=other)])
    return redirect("chat:thread", pk=conv.pk)
