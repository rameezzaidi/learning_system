import os

from django.conf import settings
from django.db import models
from django.utils import timezone

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


class Conversation(models.Model):
    """A one-to-one chat (is_group=False, unique direct_key) or a named group."""

    title = models.CharField(max_length=80, blank=True)
    is_group = models.BooleanField(default=False)
    direct_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    @staticmethod
    def key_for(a_id, b_id):
        lo, hi = sorted((a_id, b_id))
        return f"{lo}-{hi}"

    def other_user(self, me):
        if self.is_group:
            return None
        for p in self.participants.all():
            if p.user_id != me.id:
                return p.user
        return None

    def name_for(self, me):
        if self.is_group:
            return self.title or "Group chat"
        o = self.other_user(me)
        return o.display_name if o else "Chat"

    def __str__(self):
        return self.title or f"Chat {self.pk}"


class Participant(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_memberships")
    last_read_at = models.DateTimeField(default=timezone.now)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("conversation", "user")


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    body = models.TextField(blank=True, max_length=4000)
    attachment = models.FileField(upload_to="chat/%Y/%m/", blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]

    @property
    def attachment_name(self):
        return os.path.basename(self.attachment.name) if self.attachment else ""

    @property
    def is_image(self):
        return bool(self.attachment) and os.path.splitext(self.attachment.name)[1].lower() in IMAGE_EXT
