"""Which campuses / students a user may see.

None  = unrestricted (Super Admin, Head Office, and anyone not management).
list  = only these campus ids (Regional Director: the region's campuses; Principal: own campus).
"""
from accounts.models import User


def campus_ids(user):
    """Campus ids visible to a management user, or None for 'all'."""
    from organization.models import Campus
    if user.is_super_admin or user.role == User.Role.HEAD_OFFICE:
        return None
    if user.role == User.Role.REGIONAL:
        return list(Campus.objects.filter(region_id=user.region_id).values_list("pk", flat=True)) if user.region_id else []
    if user.role == User.Role.PRINCIPAL:
        return [user.campus_id] if user.campus_id else []
    if user.role == User.Role.TEACHER and user.campus_id:  # only matters if an admin grants a teacher list permissions
        return [user.campus_id]
    return None


def campuses_for(user):
    from organization.models import Campus
    ids = campus_ids(user)
    qs = Campus.objects.select_related("region")
    return qs if ids is None else qs.filter(pk__in=ids)


def students_for(user):
    qs = User.objects.filter(role=User.Role.STUDENT).select_related("student_profile__campus__region")
    ids = campus_ids(user)
    return qs if ids is None else qs.filter(student_profile__campus_id__in=ids)


def can_see_student(user, student):
    if not user.is_management:
        return True
    ids = campus_ids(user)
    if ids is None:
        return True
    cid = getattr(getattr(student, "student_profile", None), "campus_id", None)
    return cid in ids


def classes_for(user):
    from academics.models import SchoolClass
    from django.db.models import Q
    ids = campus_ids(user) if user.is_management else None
    qs = SchoolClass.objects.all()
    return qs if ids is None else qs.filter(Q(campus_id__in=ids) | Q(campus__isnull=True))
