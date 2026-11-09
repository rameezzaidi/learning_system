"""Fee rules in one place: amounts, monthly generation (idempotent, with catch-up), balances, payments."""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import User
from core.notify import notify_family

from .models import FeeDefault, LedgerEntry, StudentFeePlan

ZERO = Decimal("0")


def first_of(d):
    return d.replace(day=1)


def next_month(d):
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def months_between(start, end):
    m = first_of(start)
    end = first_of(end)
    while m <= end:
        yield m
        m = next_month(m)


def class_default(student):
    from academics.models import Enrollment
    e = Enrollment.objects.filter(student=student).select_related("school_class").first()
    if not e:
        return None
    fd = FeeDefault.objects.filter(school_class=e.school_class).first()
    return fd.monthly_amount if fd else None


def monthly_amount(student, plan=None):
    """What the student is billed each month, or None when no fee is set anywhere."""
    plan = plan or StudentFeePlan.objects.filter(student=student).first()
    base = plan.monthly_amount if plan and plan.monthly_amount is not None else class_default(student)
    if base is None:
        return None
    return max(base - (plan.discount if plan else ZERO), ZERO)


def _sums(qs):
    return qs.filter(is_void=False).aggregate(
        d=Coalesce(Sum("debit"), ZERO, output_field=DecimalField()), c=Coalesce(Sum("credit"), ZERO, output_field=DecimalField()))


def balance(student):
    s = _sums(LedgerEntry.objects.filter(student=student))
    return s["d"] - s["c"]


def ledger_rows(student):
    """All entries oldest first, with a running balance (void entries shown but not counted)."""
    run, rows = ZERO, []
    for e in LedgerEntry.objects.filter(student=student).select_related("created_by"):
        if not e.is_void:
            run += e.debit - e.credit
        rows.append({"e": e, "balance": run})
    return rows


def generate(month=None, students=None, by=None, notify=True):
    """Bill every active student for `month` (default: this month), catching up months not yet billed
    since their plan's start month. Safe to run any number of times."""
    from academics.models import Enrollment
    today = timezone.localdate()
    target = first_of(month or today)
    if students is None:
        students = User.objects.filter(role=User.Role.STUDENT, is_active=True, enrollment__isnull=False)
    created = students_billed = skipped = 0
    for st in students:
        plan = StudentFeePlan.objects.filter(student=st).first()
        if plan is None:
            if class_default(st) is None:
                skipped += 1
                continue
            plan = StudentFeePlan.objects.create(student=st, start_month=target)
        if not plan.is_active:
            skipped += 1
            continue
        amount = monthly_amount(st, plan)
        if not amount:
            skipped += 1
            continue
        billed_here = []
        for m in months_between(plan.start_month, target):
            with transaction.atomic():
                _, made = LedgerEntry.objects.get_or_create(
                    student=st, month=m, kind=LedgerEntry.Kind.MONTHLY, is_void=False,
                    defaults={"entry_date": m, "debit": amount, "description": f"Monthly fee {m:%B %Y}", "created_by": by})
            if made:
                created += 1
                billed_here.append(m)
        if billed_here:
            students_billed += 1
            if notify:
                bal = balance(st)
                notify_family(st, f"Fee for {billed_here[-1]:%B %Y} added", f"Monthly fee {amount}. Outstanding balance: {bal}.",
                              "/fees/me/", f"/fees/student/{st.pk}/", "fees")
    return {"entries": created, "students": students_billed, "skipped": skipped, "month": target}


def record_payment(student, amount, method, reference="", entry_date=None, by=None, note=""):
    with transaction.atomic():
        e = LedgerEntry.objects.create(student=student, entry_date=entry_date or timezone.localdate(), kind=LedgerEntry.Kind.PAYMENT,
                                       credit=amount, method=method, reference=reference, description=note or "Payment received", created_by=by)
        e.receipt_no = f"R-{e.pk:06d}"
        e.save(update_fields=["receipt_no"])
    notify_family(student, "Payment received", f"{amount} received. Receipt {e.receipt_no}. Balance now {balance(student)}.",
                  "/fees/me/", f"/fees/student/{student.pk}/", "fees")
    return e


def add_entry(student, kind, amount, description, by=None, entry_date=None):
    """Other charge (debit) or discount (credit)."""
    kw = {"debit": amount} if kind == LedgerEntry.Kind.CHARGE else {"credit": amount}
    return LedgerEntry.objects.create(student=student, entry_date=entry_date or timezone.localdate(), kind=kind, description=description[:200], created_by=by, **kw)


def void(entry, reason, by):
    if entry.is_void:
        return entry
    entry.is_void, entry.void_reason, entry.voided_by, entry.voided_at = True, reason[:200], by, timezone.now()
    entry.save(update_fields=["is_void", "void_reason", "voided_by", "voided_at"])
    return entry


def summary(student):
    last_pay = LedgerEntry.objects.filter(student=student, kind="payment", is_void=False).order_by("-entry_date", "-id").first()
    plan = StudentFeePlan.objects.filter(student=student).first()
    return {"balance": balance(student), "monthly": monthly_amount(student, plan), "plan": plan, "last_payment": last_pay,
            "recent": ledger_rows(student)[-6:][::-1]}


def dashboard(students_qs, month=None):
    """Totals and defaulters for the given (already scoped) students."""
    month = first_of(month or timezone.localdate())
    ids = list(students_qs.values_list("pk", flat=True))
    base = LedgerEntry.objects.filter(student_id__in=ids, is_void=False)
    billed = base.filter(month=month, kind="monthly").aggregate(t=Coalesce(Sum("debit"), ZERO, output_field=DecimalField()))["t"]
    collected = base.filter(kind="payment", entry_date__year=month.year, entry_date__month=month.month).aggregate(
        t=Coalesce(Sum("credit"), ZERO, output_field=DecimalField()))["t"]
    rows = (students_qs.annotate(
        owed=Coalesce(Sum("ledger__debit", filter=Q(ledger__is_void=False)), ZERO, output_field=DecimalField()),
        paid=Coalesce(Sum("ledger__credit", filter=Q(ledger__is_void=False)), ZERO, output_field=DecimalField())))
    defaulters = []
    outstanding = ZERO
    for u in rows:
        bal = u.owed - u.paid
        if bal > 0:
            outstanding += bal
            defaulters.append((u, bal))
    defaulters.sort(key=lambda t: -t[1])
    return {"month": month, "billed": billed, "collected": collected, "outstanding": outstanding, "defaulters": defaulters}


def auto_generate():
    """Called from the dashboard. Cheap guard so the full pass runs at most every 6 hours per month."""
    from django.conf import settings
    from django.core.cache import cache
    if not getattr(settings, "FEES_AUTO_GENERATE", False):
        return None
    key = f"fees:auto:{timezone.localdate():%Y-%m}"
    if not cache.add(key, 1, 6 * 3600):
        return None
    try:
        return generate()
    except Exception:  # billing must never break the dashboard
        import logging
        logging.getLogger(__name__).exception("auto fee generation failed")
        cache.delete(key)
        return None
