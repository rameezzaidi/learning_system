"""Shared student filtering, used by the Students page and the Student Report."""
from django.db.models import Q

from accounts.models import User

SORTS = {
    "name": ("first_name", "last_name", "username"),
    "admission": ("student_profile__admission_no",),
    "region": ("student_profile__campus__region__name",),
    "campus": ("student_profile__campus__name",),
    "status": ("is_active",),
    "source": ("student_profile__source",),
}


def student_queryset(g, user=None):
    """Filter students by the GET-style mapping `g` (region, campus, source, status, q)."""
    from core.scope import students_for
    qs = students_for(user) if user is not None else User.objects.filter(role=User.Role.STUDENT).select_related("student_profile__campus__region")
    region, campus, source, status, q = (g.get(k, "") for k in ("region", "campus", "source", "status", "q"))
    if region.isdigit():
        qs = qs.filter(student_profile__campus__region_id=region)
    if campus == "none":
        qs = qs.filter(Q(student_profile__isnull=True) | Q(student_profile__campus__isnull=True))
    elif campus.isdigit():
        qs = qs.filter(student_profile__campus_id=campus)
    if source == "oracle":
        qs = qs.filter(student_profile__source="oracle")
    elif source == "manual":
        qs = qs.filter(Q(student_profile__isnull=True) | Q(student_profile__source="manual"))
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    if q:
        qs = qs.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
            | Q(student_profile__admission_no__icontains=q)
        )
    return qs


def sort_queryset(qs, sort, direction):
    fields = SORTS.get(sort, SORTS["name"])
    if direction == "desc":
        fields = tuple("-" + f for f in fields)
    return qs.order_by(*fields, "pk")
