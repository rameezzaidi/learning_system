from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from core import audit, scope

from . import services
from .models import DOC_KINDS, Admission, StudentDocument, TransferCertificate


def _need_manage(u):
    if not services.can_manage(u):
        raise PermissionDenied


def _need_view(u):
    if not services.can_view(u):
        raise PermissionDenied


def _student(user, pk):
    st = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    if not (user.is_super_admin or (user.is_management and scope.can_see_student(user, st))):
        raise PermissionDenied
    return st


@login_required
def admissions(request):
    _need_view(request.user)
    status = request.GET.get("status", "")
    qs = services.admissions_for(request.user)
    if status in dict(Admission.Status.choices):
        qs = qs.filter(status=status)
    counts = {s: services.admissions_for(request.user).filter(status=s).count() for s, _ in Admission.Status.choices}
    return render(request, "sis/admissions.html", {"rows": qs[:200], "status": status, "statuses": Admission.Status.choices, "counts": counts,
                                                  "can_manage": services.can_manage(request.user), "page": "admissions"})


def _classes_campuses(user):
    from academics.models import SchoolClass
    return scope.classes_for(user).select_related("campus") if user.is_management else SchoolClass.objects.select_related("campus"), scope.campuses_for(user)


@login_required
def admission_new(request):
    _need_manage(request.user)
    classes, campuses = _classes_campuses(request.user)
    if request.method == "POST":
        p = request.POST
        name, guardian = p.get("applicant_name", "").strip(), p.get("guardian_name", "").strip()
        if not (name and guardian):
            messages.error(request, "Applicant name and guardian name are required.")
        else:
            try:
                dob = date.fromisoformat(p.get("date_of_birth", "")) if p.get("date_of_birth") else None
            except ValueError:
                dob = None
            camp = campuses.filter(pk=p.get("campus") or 0).first()
            cls = classes.filter(pk=p.get("applying_class") or 0).first()
            a = Admission.objects.create(applicant_name=name[:120], date_of_birth=dob, guardian_name=guardian[:120], guardian_phone=p.get("guardian_phone", "")[:30],
                                         guardian_email=p.get("guardian_email", "")[:254], previous_school=p.get("previous_school", "")[:160],
                                         campus=camp, applying_class=cls, notes=p.get("notes", ""), created_by=request.user)
            audit.record(request, "admission.create", name)
            messages.success(request, "Inquiry recorded.")
            return redirect("sis:admission", pk=a.pk)
    return render(request, "sis/admission_new.html", {"classes": classes, "campuses": campuses, "page": "admissions"})


@login_required
def admission(request, pk):
    _need_view(request.user)
    a = get_object_or_404(services.admissions_for(request.user), pk=pk)
    creds = request.session.pop("admit_creds", None) if request.session.get("admit_creds", {}).get("adm") == a.pk else None
    if request.method == "POST":
        _need_manage(request.user)
        act = request.POST.get("action")
        if act == "status" and a.status != Admission.Status.ADMITTED:
            new = request.POST.get("status")
            if new in dict(Admission.Status.choices) and new != Admission.Status.ADMITTED:
                a.status, a.notes = new, request.POST.get("notes", a.notes)
                a.save()
                audit.record(request, "admission.status", a.applicant_name, new)
        elif act == "class":
            classes, _ = _classes_campuses(request.user)
            a.applying_class = classes.filter(pk=request.POST.get("applying_class") or 0).first() or a.applying_class
            a.save()
        elif act == "admit":
            try:
                st, pw, par, ppw = services.admit(a, request.user, create_parent=bool(request.POST.get("create_parent")))
            except ValueError as e:
                messages.error(request, str(e))
            else:
                audit.record(request, "admission.admit", a.applicant_name, st.username)
                request.session["admit_creds"] = {"adm": a.pk, "student": st.username, "spw": pw, "parent": par.username if par else "", "ppw": ppw}
                messages.success(request, f"{st.display_name} is admitted.")
        return redirect("sis:admission", pk=a.pk)
    classes, _ = _classes_campuses(request.user)
    return render(request, "sis/admission.html", {"a": a, "creds": creds, "classes": classes, "statuses": Admission.Status.choices,
                                                 "can_manage": services.can_manage(request.user), "page": "admissions"})


@login_required
def documents(request, pk):
    st = _student(request.user, pk)
    if not services.can_view(request.user) and not request.user.is_super_admin:
        raise PermissionDenied
    if request.method == "POST":
        _need_manage(request.user)
        if request.POST.get("action") == "delete":
            d = get_object_or_404(StudentDocument, pk=request.POST.get("id") or 0, student=st)
            audit.record(request, "document.delete", st.username, d.filename)
            d.file.delete(save=False)
            d.delete()
            messages.success(request, "Document removed.")
        else:
            f = request.FILES.get("file")
            err = services.check_upload(f) if f else "Choose a file."
            if err:
                messages.error(request, err)
            else:
                kind = request.POST.get("kind") if request.POST.get("kind") in dict(DOC_KINDS) else "other"
                d = StudentDocument.objects.create(student=st, kind=kind, file=f, note=request.POST.get("note", "")[:160], uploaded_by=request.user)
                audit.record(request, "document.upload", st.username, d.get_kind_display())
                messages.success(request, "Document uploaded.")
        return redirect("sis:documents", pk=st.pk)
    return render(request, "sis/documents.html", {"student": st, "docs": st.documents.all(), "kinds": DOC_KINDS, "can_manage": services.can_manage(request.user), "page": "students"})


@login_required
def document_file(request, pk):
    d = get_object_or_404(StudentDocument.objects.select_related("student"), pk=pk)
    _student(request.user, d.student_id)
    if not services.can_view(request.user):
        raise PermissionDenied
    audit.record(request, "document.view", d.student.username, d.filename)
    try:
        resp = FileResponse(d.file.open("rb"), as_attachment=False, filename=d.filename)
    except FileNotFoundError:
        raise Http404
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Security-Policy"] = "sandbox"
    return resp


@login_required
def promotion(request):
    _need_manage(request.user)
    from academics.models import Enrollment
    classes, _ = _classes_campuses(request.user)
    src = classes.filter(pk=request.GET.get("from") or request.POST.get("from") or 0).first()
    if request.method == "POST":
        to = classes.filter(pk=request.POST.get("to") or 0).first()
        ids = [int(x) for x in request.POST.getlist("student") if x.isdigit()]
        allowed = set(Enrollment.objects.filter(school_class=src, student_id__in=ids).values_list("student_id", flat=True)) if src else set()
        if not (src and to and allowed) or src.pk == to.pk:
            messages.error(request, "Choose a source class, a different target class and at least one student.")
        else:
            n = services.promote(allowed, to, request.user)
            audit.record(request, "promotion", f"{src} → {to}", f"{n} students")
            messages.success(request, f"{n} student(s) moved from {src} to {to}. Their history stays intact.")
            return redirect("sis:promotion")
    students = User.objects.filter(role=User.Role.STUDENT, is_active=True, enrollment__school_class=src).order_by("first_name") if src else []
    return render(request, "sis/promotion.html", {"classes": classes, "src": src, "students": students, "page": "promotion"})


@login_required
def tc_issue(request, pk):
    _need_manage(request.user)
    st = _student(request.user, pk)
    if request.method == "POST":
        if not request.POST.get("confirm"):
            messages.error(request, "Tick the confirmation box. Issuing a certificate deactivates the student's account.")
        else:
            tc = services.issue_tc(st, request.user, request.POST.get("reason", ""), request.POST.get("destination", ""), request.POST.get("conduct", "Good"))
            audit.record(request, "tc.issue", st.username, tc.number)
            return redirect("sis:tc", pk=tc.pk)
    return render(request, "sis/tc_form.html", {"student": st, "page": "students"})


@login_required
def tc(request, pk):
    t = get_object_or_404(TransferCertificate.objects.select_related("student__student_profile__campus"), pk=pk)
    _student(request.user, t.student_id)
    _need_view(request.user)
    return render(request, "sis/tc.html", {"t": t, "page": "students"})
