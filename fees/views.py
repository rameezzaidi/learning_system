import csv
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.rbac import has_perm, perm_required
from core import audit, scope

from . import services
from .forms import EntryForm, PaymentForm, PlanForm
from .models import FeeDefault, LedgerEntry, StudentFeePlan


def can_view(user, student):
    if user.is_super_admin or user.pk == student.pk:
        return True
    if user.is_parent:
        return user.children.filter(pk=student.pk).exists()
    if user.is_management and has_perm(user, "fees.view"):
        return scope.can_see_student(user, student)
    return False


def can_act(user, student, code):
    if user.is_super_admin:
        return True
    return user.is_management and has_perm(user, code) and scope.can_see_student(user, student)


def _student(request, pk):
    student = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    if not can_view(request.user, student):
        raise PermissionDenied
    return student


def _csv_safe(v):
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v


def _month(request):
    raw = request.GET.get("month") or request.POST.get("month") or ""
    try:
        y, m = raw.split("-")
        return date(int(y), int(m), 1)
    except (ValueError, TypeError):
        return services.first_of(timezone.localdate())


# ------------------------------------------------------------------ staff dashboard
@login_required
@perm_required("fees.view")
def dashboard(request):
    from django.db.models import Q
    month = _month(request)
    students = scope.students_for(request.user).filter(is_active=True)
    q, campus = request.GET.get("q", "").strip(), request.GET.get("campus", "")
    if campus.isdigit():
        students = students.filter(student_profile__campus_id=campus)
    if q:
        students = students.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(student_profile__admission_no__icontains=q))
    d = services.dashboard(students, month)
    if request.GET.get("format") == "csv":
        audit.record(request, "export.fees", "defaulters", f"{len(d['defaulters'])} rows")
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="fee-defaulters.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Admission no", "Student", "Campus", "Monthly fee", "Outstanding"])
        for u, bal in d["defaulters"]:
            p = getattr(u, "student_profile", None)
            w.writerow([_csv_safe(x) for x in (p.admission_no if p else "", u.display_name, p.campus.name if p and p.campus else "", services.monthly_amount(u) or "", bal)])
        return resp
    return render(request, "fees/dashboard.html", {
        "d": d, "defaulters": [(u, bal, services.monthly_amount(u)) for u, bal in d["defaulters"][:100]], "n_def": len(d["defaulters"]), "q": q, "campus": campus, "campuses": scope.campuses_for(request.user),
        "can_manage": has_perm(request.user, "fees.manage"), "month_value": f"{month:%Y-%m}", "page": "fees"})


@login_required
@perm_required("fees.manage")
@require_POST
def generate(request):
    month = _month(request)
    students = None
    if request.user.is_management:
        students = scope.students_for(request.user).filter(is_active=True, enrollment__isnull=False)
    r = services.generate(month, students=students, by=request.user)
    audit.record(request, "fees.generate", f"{month:%Y-%m}", f"{r['entries']} entries, {r['students']} students")
    messages.success(request, f"{r['entries']} fee entr{'y' if r['entries'] == 1 else 'ies'} created for {r['students']} student{'s' if r['students'] != 1 else ''}"
                              f"{' (' + str(r['skipped']) + ' without a fee set)' if r['skipped'] else ''}.")
    return redirect(f"/fees/?month={month:%Y-%m}")


@login_required
@perm_required("fees.manage")
def defaults(request):
    classes = scope.classes_for(request.user).select_related("campus")
    if request.method == "POST":
        n = 0
        for c in classes:
            raw = (request.POST.get(f"c{c.pk}") or "").strip()
            if raw == "":
                FeeDefault.objects.filter(school_class=c).delete()
                continue
            try:
                amt = round(float(raw), 2)
            except ValueError:
                continue
            if amt < 0:
                continue
            FeeDefault.objects.update_or_create(school_class=c, defaults={"monthly_amount": amt})
            n += 1
        audit.record(request, "fees.defaults", "class fees", f"{n} classes")
        messages.success(request, "Class fees saved. They apply to the next monthly generation.")
        return redirect("fees:defaults")
    cur = {f.school_class_id: f.monthly_amount for f in FeeDefault.objects.all()}
    return render(request, "fees/defaults.html", {"rows": [(c, cur.get(c.pk, "")) for c in classes], "page": "fees"})


# ------------------------------------------------------------------ student ledger
@login_required
def my(request):
    u = request.user
    if u.is_student:
        return redirect("fees:ledger", pk=u.pk)
    if u.is_parent:
        kid = u.children.first()
        if kid:
            return redirect("fees:ledger", pk=kid.pk)
    raise PermissionDenied


@login_required
def ledger(request, pk):
    student = _student(request, pk)
    me = request.user
    rows = services.ledger_rows(student)
    smry = services.summary(student)
    return render(request, "fees/ledger.html", {
        "student": student, "rows": list(reversed(rows)), "s": smry,
        "can_collect": can_act(me, student, "fees.collect"), "can_manage": can_act(me, student, "fees.manage"),
        "pay_form": PaymentForm(initial={"entry_date": timezone.localdate()}), "entry_form": EntryForm(),
        "plan_form": PlanForm(instance=smry["plan"] or StudentFeePlan(start_month=services.first_of(timezone.localdate()))),
        "class_fee": services.class_default(student), "kids": list(me.children.all()) if me.is_parent else [],
        "page": "fees", "active_child": student.pk})


def _need(request, student, code):
    if not can_act(request.user, student, code):
        raise PermissionDenied


@login_required
@require_POST
def pay(request, pk):
    student = _student(request, pk)
    _need(request, student, "fees.collect")
    f = PaymentForm(request.POST)
    if f.is_valid():
        d = f.cleaned_data
        e = services.record_payment(student, d["amount"], d["method"], d["reference"], d["entry_date"], request.user, d["note"])
        audit.record(request, "fees.payment", student.username, f"{d['amount']} {d['method']} {e.receipt_no}")
        messages.success(request, f"Payment recorded. Receipt {e.receipt_no}.")
    else:
        messages.error(request, "Payment not saved: " + "; ".join(f"{k}: {v[0]}" for k, v in f.errors.items()))
    return redirect("fees:ledger", pk=student.pk)


@login_required
@require_POST
def entry(request, pk):
    student = _student(request, pk)
    _need(request, student, "fees.manage")
    f = EntryForm(request.POST)
    if f.is_valid():
        d = f.cleaned_data
        services.add_entry(student, d["kind"], d["amount"], d["description"], request.user)
        audit.record(request, f"fees.{d['kind']}", student.username, f"{d['amount']} {d['description']}")
        messages.success(request, "Entry added.")
    else:
        messages.error(request, "Entry not saved: " + "; ".join(f"{k}: {v[0]}" for k, v in f.errors.items()))
    return redirect("fees:ledger", pk=student.pk)


@login_required
@require_POST
def void(request, pk):
    e = get_object_or_404(LedgerEntry, pk=pk)
    student = _student(request, e.student_id)
    _need(request, student, "fees.manage")
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Please give a reason for voiding.")
    else:
        services.void(e, reason, request.user)
        audit.record(request, "fees.void", student.username, f"entry {e.pk}: {reason}")
        messages.success(request, "Entry voided. It stays in the ledger but no longer counts.")
    return redirect("fees:ledger", pk=student.pk)


@login_required
@require_POST
def plan(request, pk):
    student = _student(request, pk)
    _need(request, student, "fees.manage")
    obj = StudentFeePlan.objects.filter(student=student).first() or StudentFeePlan(student=student)
    f = PlanForm(request.POST, instance=obj)
    if f.is_valid():
        f.save()
        audit.record(request, "fees.plan", student.username, f"amount={f.cleaned_data['monthly_amount']} discount={f.cleaned_data['discount']}")
        messages.success(request, "Fee plan saved. It applies from the start month.")
    else:
        messages.error(request, "Plan not saved: " + "; ".join(f"{k}: {v[0]}" for k, v in f.errors.items()))
    return redirect("fees:ledger", pk=student.pk)


@login_required
def receipt(request, pk):
    e = get_object_or_404(LedgerEntry, pk=pk, kind="payment", is_void=False)
    student = _student(request, e.student_id)
    return render(request, "fees/receipt.html", {"e": e, "student": student, "balance": services.balance(student),
                                                 "class": services_class(student), "page": "fees"})


def services_class(student):
    from academics.models import student_class
    return student_class(student)
