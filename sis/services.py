import re
import secrets
from datetime import date

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from accounts.rbac import has_perm
from core import scope

from .models import ALLOWED_EXT, MAX_BYTES, Admission, PromotionLog, TransferCertificate
import os


def admissions_for(user):
    qs = Admission.objects.select_related("campus", "applying_class")
    ids = scope.campus_ids(user) if user.is_management else None
    return qs if ids is None else qs.filter(campus_id__in=ids)


def can_manage(user):
    return user.is_super_admin or (user.is_management and has_perm(user, "sis.manage"))


def can_view(user):
    return user.is_super_admin or (user.is_management and has_perm(user, "sis.view"))


def _username(name):
    base = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")[:20] or "student"
    u, n = base, 1
    while User.objects.filter(username=u).exists():
        n += 1
        u = f"{base}{n}"
    return u


def _password():
    return secrets.token_urlsafe(9)


@transaction.atomic
def admit(adm, by, create_parent=True):
    """Create the student (+ profile, enrolment, parent account). Returns (student, student_pw, parent, parent_pw)."""
    from academics.models import Enrollment
    from organization.models import StudentProfile
    if adm.status == Admission.Status.ADMITTED or adm.student_id:
        raise ValueError("Already admitted.")
    if adm.applying_class_id is None:
        raise ValueError("Choose the class first.")
    parts = adm.applicant_name.split()
    pw = _password()
    st = User.objects.create_user(username=_username(adm.applicant_name), password=pw, role=User.Role.STUDENT,
                                  first_name=parts[0][:150] if parts else "", last_name=" ".join(parts[1:])[:150])
    campus = adm.campus or adm.applying_class.campus
    StudentProfile.objects.create(user=st, campus=campus, admission_no=f"ADM-{timezone.localdate().year}-{adm.pk:04d}")
    Enrollment.objects.create(student=st, school_class=adm.applying_class)
    parent, ppw = None, ""
    if create_parent and adm.guardian_name:
        ppw = _password()
        gp = adm.guardian_name.split()
        parent = User.objects.create_user(username=_username("p." + st.username), password=ppw, role=User.Role.PARENT,
                                          first_name=gp[0][:150], last_name=" ".join(gp[1:])[:150], email=adm.guardian_email, phone=adm.guardian_phone)
        parent.children.add(st)
    adm.student, adm.status = st, Admission.Status.ADMITTED
    adm.save()
    return st, pw, parent, ppw


def check_upload(f):
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXT:
        return "Only PDF, JPG or PNG files are allowed."
    if f.size > MAX_BYTES:
        return "The file is larger than 5 MB."
    head = f.read(8)
    f.seek(0)
    ok = (ext == ".pdf" and head.startswith(b"%PDF")) or (ext in (".jpg", ".jpeg") and head.startswith(b"\xff\xd8")) or (ext == ".png" and head.startswith(b"\x89PNG"))
    return "" if ok else "The file content does not match its type."


@transaction.atomic
def promote(student_ids, to_class, by):
    from academics.models import Enrollment
    moved = 0
    for e in Enrollment.objects.filter(student_id__in=student_ids).select_related("school_class"):
        if e.school_class_id == to_class.pk:
            continue
        PromotionLog.objects.create(student_id=e.student_id, from_class=e.school_class, to_class=to_class, by=by)
        e.school_class = to_class
        e.save()
        moved += 1
    return moved


@transaction.atomic
def issue_tc(student, by, reason="", destination="", conduct="Good"):
    from academics.models import student_class
    cls = student_class(student)
    n = TransferCertificate.objects.count() + 1
    num = f"TC-{n:04d}"
    while TransferCertificate.objects.filter(number=num).exists():
        n += 1
        num = f"TC-{n:04d}"
    tc = TransferCertificate.objects.create(number=num, student=student, issued_on=timezone.localdate(), leaving_class=str(cls or ""),
                                            reason=reason[:200], destination=destination[:160], conduct=conduct[:60] or "Good", issued_by=by)
    student.is_active = False
    student.save(update_fields=["is_active"])
    return tc
