"""Who may talk to whom (school-safe by default).

Admin: everyone.  Teacher: admins, other teachers, and the students/parents of classes they teach.
Student: admins, classmates and the teachers of their class.  Parent: admins and the teachers of their children's classes.
"""
from academics.models import Course, Enrollment
from accounts.models import User


def _teacher_ids_for_classes(class_ids):
    return Course.objects.filter(school_class_id__in=class_ids, teacher__isnull=False).values_list("teacher_id", flat=True)


def allowed_users(user):
    base = User.objects.filter(is_active=True).exclude(pk=user.pk)
    admins = User.objects.filter(role=User.Role.SUPER_ADMIN, is_active=True)
    if user.is_super_admin:
        return base
    ids = set(admins.values_list("pk", flat=True))
    if user.is_management:
        ids |= set(User.objects.filter(is_active=True, role__in=[User.Role.TEACHER, User.Role.HEAD_OFFICE, User.Role.REGIONAL, User.Role.PRINCIPAL]).values_list("pk", flat=True))
    elif user.is_teacher:
        classes = list(Course.objects.filter(teacher=user).values_list("school_class_id", flat=True))
        students = list(Enrollment.objects.filter(school_class_id__in=classes).values_list("student_id", flat=True))
        ids |= set(students)
        ids |= set(User.objects.filter(children__in=students).values_list("pk", flat=True))
        ids |= set(User.objects.filter(role=User.Role.TEACHER, is_active=True).values_list("pk", flat=True))
    elif user.is_student:
        e = Enrollment.objects.filter(student=user).first()
        if e:
            ids |= set(Enrollment.objects.filter(school_class=e.school_class).values_list("student_id", flat=True))
            ids |= set(_teacher_ids_for_classes([e.school_class_id]))
    elif user.is_parent:
        classes = list(Enrollment.objects.filter(student__in=user.children.all()).values_list("school_class_id", flat=True))
        ids |= set(_teacher_ids_for_classes(classes))
    ids.discard(user.pk)
    return base.filter(pk__in=ids)


def can_chat(user, other):
    return allowed_users(user).filter(pk=other.pk).exists()
