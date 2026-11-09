from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import User
from accounts.rbac import has_perm
from core import audit, scope
from core.notify import notify

from .models import Book, Loan, Route, RouteStudent

LOAN_DAYS = 14
MAX_LOANS = 5


def fine_per_day():
    return Decimal(str(getattr(settings, "LIBRARY_FINE_PER_DAY", 5)))


def _manage_lib(u):
    return u.is_super_admin or (u.is_management and has_perm(u, "library.manage"))


def _books(u):
    qs = Book.objects.select_related("campus")
    ids = scope.campus_ids(u) if (u.is_management or u.is_teacher) else None
    return qs if ids is None else qs.filter(Q(campus__isnull=True) | Q(campus_id__in=ids))


def _find_person(raw):
    raw = (raw or "").strip()
    return User.objects.filter(is_active=True, role__in=["student", "teacher"]).filter(Q(username__iexact=raw) | Q(student_profile__admission_no__iexact=raw)).first() if raw else None


@login_required
def library(request):
    manage = _manage_lib(request.user)
    if request.method == "POST":
        if not manage:
            raise PermissionDenied
        act = request.POST.get("action")
        if act == "add":
            t = request.POST.get("title", "").strip()
            try:
                copies = max(1, min(int(request.POST.get("copies") or 1), 500))
            except ValueError:
                copies = 1
            if not t:
                messages.error(request, "Give the book a title.")
            else:
                Book.objects.create(title=t[:200], author=request.POST.get("author", "")[:120], isbn=request.POST.get("isbn", "")[:20], shelf=request.POST.get("shelf", "")[:30], copies=copies)
                audit.record(request, "library.add", t)
                messages.success(request, "Book added.")
        elif act == "issue":
            book = get_object_or_404(_books(request.user), pk=request.POST.get("book") or 0)
            who = _find_person(request.POST.get("borrower"))
            err = None
            with transaction.atomic():
                book = Book.objects.select_for_update().get(pk=book.pk)
                if who is None:
                    err = "Borrower not found. Use the username or admission number."
                elif book.available < 1:
                    err = "No copy is available."
                elif Loan.objects.filter(borrower=who, returned_on__isnull=True).count() >= MAX_LOANS:
                    err = f"{who.display_name} already has {MAX_LOANS} books out."
                else:
                    today = timezone.localdate()
                    Loan.objects.create(book=book, borrower=who, issued_on=today, due_on=today + timedelta(days=LOAN_DAYS), issued_by=request.user)
            if err:
                messages.error(request, err)
            else:
                audit.record(request, "library.issue", book.title, who.username)
                notify(who, f"Book issued: {book.title}", f"Please return by {(timezone.localdate() + timedelta(days=LOAN_DAYS)):%d %b}.", "/library/", "library")
                messages.success(request, f"Issued to {who.display_name}.")
        elif act == "return":
            loan = get_object_or_404(Loan, pk=request.POST.get("loan") or 0, returned_on__isnull=True)
            today = timezone.localdate()
            late = max((today - loan.due_on).days, 0)
            loan.returned_on, loan.fine = today, fine_per_day() * late
            loan.save()
            audit.record(request, "library.return", loan.book.title, f"{loan.borrower.username} fine {loan.fine}")
            messages.success(request, f"Returned.{f' Late fine: {loan.fine}.' if loan.fine else ''}")
        return redirect("campusops:library")
    q = request.GET.get("q", "").strip()
    books = _books(request.user)
    if q:
        books = books.filter(Q(title__icontains=q) | Q(author__icontains=q) | Q(isbn__icontains=q))
    mine = Loan.objects.filter(borrower=request.user, returned_on__isnull=True).select_related("book")
    out = Loan.objects.filter(returned_on__isnull=True).select_related("book", "borrower").order_by("due_on")[:100] if manage else []
    return render(request, "campusops/library.html", {"books": books[:100], "q": q, "mine": mine, "out": out, "manage": manage, "today": timezone.localdate(), "fine": fine_per_day(), "page": "library"})


# ------------------------------------------------------------------ transport
def _manage_tr(u):
    return u.is_super_admin or (u.is_management and has_perm(u, "transport.manage"))


def _routes(u):
    qs = Route.objects.select_related("campus").prefetch_related("riders__student")
    ids = scope.campus_ids(u) if u.is_management else None
    return qs if ids is None else qs.filter(Q(campus__isnull=True) | Q(campus_id__in=ids))


@login_required
def transport(request):
    u = request.user
    manage = _manage_tr(u)
    view = manage or (u.is_management and has_perm(u, "transport.view"))
    if not (view or u.is_student or u.is_parent):
        raise PermissionDenied
    if request.method == "POST":
        if not manage:
            raise PermissionDenied
        p = request.POST
        act = p.get("action")
        if act == "route":
            name = p.get("name", "").strip()
            campus = scope.campuses_for(u).filter(pk=p.get("campus") or 0).first()
            try:
                cap, fee = max(1, int(p.get("capacity") or 30)), max(Decimal("0"), Decimal(p.get("monthly_fee") or "0"))
            except Exception:
                cap, fee = 30, Decimal("0")
            if not name or (campus is None and u.is_management and scope.campus_ids(u) is not None):
                messages.error(request, "Give the route a name and choose a campus.")
            else:
                Route.objects.create(name=name[:80], campus=campus, vehicle_no=p.get("vehicle_no", "")[:30], driver_name=p.get("driver_name", "")[:80],
                                     driver_phone=p.get("driver_phone", "")[:30], capacity=cap, monthly_fee=fee)
                audit.record(request, "transport.route", name)
                messages.success(request, "Route added.")
        elif act == "assign":
            route = get_object_or_404(_routes(u), pk=p.get("route") or 0)
            st = User.objects.filter(role="student", is_active=True).filter(Q(username__iexact=p.get("student", "").strip()) | Q(student_profile__admission_no__iexact=p.get("student", "").strip())).first()
            if st is None or not scope.can_see_student(u, st):
                messages.error(request, "Student not found in your scope.")
            elif route.seats_left < 1 and getattr(getattr(st, "route_assignment", None), "route_id", None) != route.pk:
                messages.error(request, "This route is full.")
            else:
                RouteStudent.objects.update_or_create(student=st, defaults={"route": route, "stop": p.get("stop", "")[:80]})
                audit.record(request, "transport.assign", st.username, route.name)
                messages.success(request, f"{st.display_name} assigned to {route.name}.")
        elif act == "unassign":
            rs = RouteStudent.objects.filter(pk=p.get("id") or 0, route__in=_routes(u)).first()
            if rs:
                rs.delete()
                messages.success(request, "Removed from the route.")
        elif act == "delete_route":
            r = _routes(u).filter(pk=p.get("id") or 0).first()
            if r:
                audit.record(request, "transport.route.delete", r.name)
                r.delete()
                messages.success(request, "Route deleted.")
        return redirect("campusops:transport")
    own = None
    if u.is_student:
        own = [getattr(u, "route_assignment", None)]
    elif u.is_parent:
        own = [getattr(c, "route_assignment", None) for c in u.children.all()]
    return render(request, "campusops/transport.html", {"routes": _routes(u) if view else [], "own": [o for o in (own or []) if o], "manage": manage, "view": view,
                                                       "campuses": scope.campuses_for(u) if manage else [], "page": "transport"})
