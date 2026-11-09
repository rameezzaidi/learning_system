from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from academics.models import Course


@receiver(pre_save, sender=Course, dispatch_uid="curriculum_course_pre")
def _remember_teacher(sender, instance, **kw):
    old = None
    if instance.pk:
        old = Course.objects.filter(pk=instance.pk).values_list("teacher_id", flat=True).first()
    instance._old_teacher_id = old


@receiver(post_save, sender=Course, dispatch_uid="curriculum_course_post")
def _handover_on_change(sender, instance, created, **kw):
    """Whenever the teacher of a course changes, record a handover automatically."""
    from accounts.models import User
    from .models import Handover
    from .services import create_handover
    if created:
        return
    old_id = getattr(instance, "_old_teacher_id", None)
    if old_id == instance.teacher_id or instance.teacher_id is None:
        return
    old = User.objects.filter(pk=old_id).first() if old_id else None
    kind = Handover.Kind.TRANSFER if old else Handover.Kind.ASSIGNMENT
    # an earlier open handover for this course is superseded
    Handover.objects.filter(course=instance).exclude(status="closed").update(status="closed")
    create_handover(instance, old, instance.teacher, kind, reason="Teacher changed on the course")
