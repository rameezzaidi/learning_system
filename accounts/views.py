from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import SchoolSettings

from .decorators import role_required
from .forms import LoginForm, ProfileForm, UserCreateForm, UserEditForm
from .models import User


class LoginView(auth_views.LoginView):
    template_name = "auth/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def _key(self, request):
        ip = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", ""))
        return f"loginfail:{(request.POST.get('username') or '').strip().lower()}:{ip}"

    def post(self, request, *args, **kwargs):
        from django.conf import settings
        from django.core.cache import cache
        if cache.get(self._key(request), 0) >= settings.LOGIN_MAX_FAILURES:
            form = self.get_form()
            form.add_error(None, "Too many failed attempts. Please wait a few minutes and try again.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        from django.conf import settings
        from django.core.cache import cache
        k = self._key(self.request)
        cache.set(k, cache.get(k, 0) + 1, settings.LOGIN_LOCK_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        from django.core.cache import cache
        from django.utils import timezone
        cache.delete(self._key(self.request))
        user = form.get_user()
        tf = getattr(user, "twofactor", None) if user.pk else None
        if tf is not None and tf.enabled:
            self.request.session["pre2fa"] = {"uid": user.pk, "next": self.get_success_url(), "ts": timezone.now().timestamp()}
            return redirect("accounts:verify2fa")
        return super().form_valid(form)


@require_POST
def logout_view(request):
    from django.contrib.auth import logout

    logout(request)
    return redirect("accounts:login")



def _chart(**kw):
    import json
    return json.dumps(kw, default=float)


def _exam_avg_chart(exams, user_courses=None):
    """Subject class-average bar chart for the newest of `exams` (optionally limited to some courses)."""
    from exams import grading, insights
    for e in exams:
        res = grading.compute(e)
        subs = insights.class_insights(res, None)["subjects"]
        if user_courses is not None:
            subs = [x for x in subs if x["subject"] in user_courses]
        if subs:
            return e, _chart(type="bar", labels=[x["subject"] for x in subs], values=[x["avg_pct"] for x in subs], unit="%", max=100, ref=33,
                             refLabel="Pass", title="Class average by subject")
    return None, ""


@login_required
def dashboard(request):
    from academics.models import (
        Course, Lesson, SchoolClass, Subject, course_rows, progress_for, student_class,
    )

    from organization.models import Campus, Region, StudentProfile, SyncRun

    user = request.user
    from fees import services as _fees
    _fees.auto_generate()
    ctx = {"page": "dashboard"}
    if user.is_super_admin:
        counts = {r["role"]: r["n"] for r in User.objects.values("role").annotate(n=Count("id"))}
        ctx.update(
            counts=counts,
            total=sum(counts.values()),
            active=User.objects.filter(is_active=True).count(),
            recent=User.objects.order_by("-date_joined")[:6],
            n_classes=SchoolClass.objects.count(),
            n_subjects=Subject.objects.count(),
            n_lessons=Lesson.objects.count(),
            unassigned=Course.objects.filter(teacher__isnull=True).select_related("subject", "school_class"),
            n_regions=Region.objects.count(),
            n_campuses=Campus.objects.count(),
            last_sync=SyncRun.objects.first(),
        )
        from django.db.models import Count as _C
        from exams.models import Exam
        from exams import grading, insights
        names = {"super_admin": "Admins", "teacher": "Teachers", "student": "Students", "parent": "Parents"}
        ctx["ch_roles"] = _chart(type="donut", labels=[names.get(k) or dict(User.Role.choices).get(k, k) for k in counts], values=list(counts.values()), center=sum(counts.values()), sub="Users",
                                 colors=["var(--primary)", "#8b5cf6", "#10b981", "#f59e0b", "#f43f5e", "#06b6d4", "#64748b"][:len(counts)])
        reg = (StudentProfile.objects.filter(campus__isnull=False).values("campus__region__name").annotate(n=_C("id")).order_by("-n")[:6])
        ctx["ch_regions"] = _chart(type="hbar", labels=[r["campus__region__name"] for r in reg], values=[r["n"] for r in reg], single=True, title="Students by region")
        trend = []
        for e in Exam.objects.select_related("school_class").order_by("start_date", "id")[:8]:
            a = insights.class_insights(grading.compute(e), None)["avg_pct"]
            if a is not None:
                trend.append((e.name[:14], a))
        ctx["ch_trend"] = _chart(type="line", labels=[t[0] for t in trend], values=[t[1] for t in trend], unit="%", max=100, title="Average % by exam") if trend else ""
        template = "dashboards/superadmin.html"
    elif user.is_management:
        import json

        from organization import analytics
        rows = analytics.campus_stats(user)
        scored = [r for r in rows if r["avg_pct"] is not None]
        ctx.update(rows=rows, tot=analytics.totals(rows), risk=analytics.at_risk_students(user, 8),
                   scope_label=(user.campus.name if user.campus_id and user.role == User.Role.PRINCIPAL else
                                (f"{user.region.name} region" if user.region_id and user.role == User.Role.REGIONAL else "All campuses")),
                   ch_campus=json.dumps({"type": "hbar", "labels": [r["campus"].name for r in scored], "values": [r["avg_pct"] for r in scored],
                                         "unit": "%", "max": 100, "single": True, "title": "Average exam % by campus"}, default=float) if scored else "")
        template = "dashboards/management.html"
    elif user.is_teacher:
        ctx["courses"] = Course.objects.filter(teacher=user).select_related("subject", "school_class").annotate(
            n_lessons=Count("lessons", distinct=True)
        )
        from exams.models import Exam
        cs = list(ctx["courses"])
        ctx["ch_lessons"] = _chart(type="hbar", labels=[c.subject.name for c in cs], values=[c.n_lessons for c in cs], single=True, title="Lessons per course") if cs else ""
        exams = Exam.objects.filter(papers__course__teacher=user).distinct().order_by("-start_date", "-id")
        ctx["exam_chart_exam"], ctx["ch_exam"] = _exam_avg_chart(exams, {c.subject.name for c in cs})
        template = "dashboards/teacher.html"
    elif user.is_parent:
        kids = []
        for c in user.children.all():
            cls = student_class(c)
            courses = cls.courses.all() if cls else []
            rows = [progress_for(c, co) for co in courses]
            done = sum(r["done"] for r in rows)
            total = sum(r["total"] for r in rows)
            kids.append({"student": c, "cls": cls, "n_courses": len(rows),
                         "pct": round(done * 100 / total) if total else 0, "done": done, "total": total})
        ctx["kids"] = kids
        ctx["ch_kids"] = _chart(type="hbar", labels=[k["student"].display_name for k in kids], values=[k["pct"] for k in kids], unit="%", max=100, single=True,
                                title="Lesson progress") if kids else ""
        template = "dashboards/parent.html"
    else:
        cls = student_class(user)
        ctx["guardians"] = user.parents.all()
        ctx["cls"] = cls
        ctx["rows"] = course_rows(user, cls.courses.select_related("subject", "teacher")) if cls else []
        from exams.models import Exam
        from exams import grading, insights
        ctx["ch_progress"] = _chart(type="hbar", labels=[r["course"].subject.name for r in ctx["rows"]], values=[r["pct"] for r in ctx["rows"]], unit="%", max=100,
                                    title="Lesson progress") if ctx["rows"] else ""
        ctx["ch_marks"] = ""
        if cls:
            for e in Exam.objects.filter(school_class=cls, is_published=True):
                res = grading.compute(e)
                row = grading.row_for(res, user.id)
                if row:
                    ins = insights.student_insights(res, row, None)
                    ctx["exam_name"] = e.name
                    ctx["ch_marks"] = _chart(type="bar", labels=[x["subject"] for x in ins["subjects"]], values=[x["pct"] for x in ins["subjects"]], unit="%", max=100,
                                             ref=33, refLabel="Pass", title="Latest exam")
                    ctx["overall"] = ins["overall_pct"]; ctx["grade"] = ins["grade"]
                    break
        from nuggets.models import StudentNugget
        ctx["nug"] = list(StudentNugget.objects.filter(student=user, status="assigned", nugget__is_published=True, nugget__review="approved").select_related("nugget__course__subject")[:3])
        template = "dashboards/student.html"
    return render(request, template, ctx)


@login_required
def profile(request):
    allow = SchoolSettings.load().allow_user_theme
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user, allow_theme=allow)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form, "page": "profile", "allow_theme": allow})


class PasswordView(auth_views.PasswordChangeView):
    template_name = "accounts/password.html"
    success_url = "/profile/"

    def form_valid(self, form):
        messages.success(self.request, "Password changed.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page"] = "profile"
        for f in ctx["form"].fields.values():
            f.widget.attrs["class"] = "input"
        return ctx


# ---------- Super admin: user management ----------

@login_required
@role_required("super_admin")
def user_list(request):
    role = request.GET.get("role", "")
    q = request.GET.get("q", "").strip()
    users = User.objects.all()
    if role in dict(User.Role.choices):
        users = users.filter(role=role)
    if q:
        from django.db.models import Q

        users = users.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
        )
    return render(request, "accounts/user_list.html", {
        "users": users.prefetch_related("children"), "role": role, "q": q,
        "roles": User.Role.choices, "page": "users",
    })


@login_required
@role_required("super_admin")
def user_create(request):
    initial = {"role": request.GET.get("role", User.Role.STUDENT), "is_active": True}
    form = UserCreateForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        from core import audit
        audit.record(request, "user.create", user.username, f"role={user.role}")
        messages.success(request, f"{user.display_name} created as {user.get_role_display()}.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "page": "users", "title": "Add user"})


@login_required
@role_required("super_admin")
def user_edit(request, pk):
    obj = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        old_role = obj.role
        form.save()
        from core import audit
        audit.record(request, "user.edit", obj.username, f"role {old_role}→{obj.role}" if old_role != obj.role else "")
        messages.success(request, "User updated.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {
        "form": form, "page": "users", "title": f"Edit {obj.display_name}", "obj": obj,
    })


@login_required
@role_required("super_admin")
@require_POST
def user_toggle(request, pk):
    obj = get_object_or_404(User, pk=pk)
    if obj.pk == request.user.pk:
        messages.error(request, "You cannot deactivate your own account.")
    else:
        obj.is_active = not obj.is_active
        obj.save(update_fields=["is_active"])
        from core import audit
        audit.record(request, "user.activate" if obj.is_active else "user.deactivate", obj.username)
        messages.success(request, f"{obj.display_name} is now {'active' if obj.is_active else 'inactive'}.")
    return redirect("accounts:user_list")


# ------------------------------------------------------------------ security: two-factor and sessions
def verify2fa(request):
    from django.conf import settings
    from django.contrib.auth import login
    from django.core.cache import cache
    from django.utils import timezone
    from django.utils.http import url_has_allowed_host_and_scheme

    from core import audit

    from . import twofa
    pre = request.session.get("pre2fa")
    if not pre or timezone.now().timestamp() - pre.get("ts", 0) > 300:
        request.session.pop("pre2fa", None)
        return redirect("accounts:login")
    user = get_object_or_404(User, pk=pre["uid"], is_active=True)
    key = f"2fafail:{user.pk}"
    error = ""
    if request.method == "POST":
        if cache.get(key, 0) >= settings.LOGIN_MAX_FAILURES:
            error = "Too many wrong codes. Please wait a few minutes and sign in again."
        else:
            code = request.POST.get("code", "")
            tf = user.twofactor
            ok = twofa.verify(tf.secret, code)
            if not ok:
                h = twofa.hash_code(code)
                if h in tf.backup_hashes:
                    tf.backup_hashes = [x for x in tf.backup_hashes if x != h]
                    tf.save(update_fields=["backup_hashes"])
                    audit.record(request, "2fa.backup_used", user.username, user=user)
                    ok = True
            if ok:
                cache.delete(key)
                nxt = pre.get("next") or "/"
                request.session.pop("pre2fa", None)
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                return redirect(nxt if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) else "/")
            cache.set(key, cache.get(key, 0) + 1, settings.LOGIN_LOCK_SECONDS)
            audit.record(request, "2fa.failed", user.username, user=user)
            error = "That code is not right. Try again."
    return render(request, "auth/verify.html", {"error": error, "username": user.username})


@login_required
def security(request):
    from django.contrib.sessions.models import Session

    from .models import UserSession
    if request.method == "POST":
        act = request.POST.get("action")
        if act == "revoke":
            us = UserSession.objects.filter(user=request.user, pk=request.POST.get("id") or 0).exclude(session_key=request.session.session_key).first()
            if us:
                Session.objects.filter(session_key=us.session_key).delete()
                us.delete()
                messages.success(request, "That device was signed out.")
        elif act == "revoke_others":
            others = UserSession.objects.filter(user=request.user).exclude(session_key=request.session.session_key)
            Session.objects.filter(session_key__in=list(others.values_list("session_key", flat=True))).delete()
            n = others.count()
            others.delete()
            messages.success(request, f"Signed out {n} other device(s).")
        return redirect("accounts:security")
    tf = getattr(request.user, "twofactor", None)
    return render(request, "accounts/security.html", {
        "tf": tf, "enabled": bool(tf and tf.enabled), "sessions": request.user.login_sessions.all()[:20],
        "current": request.session.session_key, "backup_left": len(tf.backup_hashes) if tf else 0, "page": "security"})


@login_required
def twofa_setup(request):
    from django.conf import settings
    from django.utils import timezone

    from core import audit

    from . import twofa
    from .models import TwoFactor
    tf = getattr(request.user, "twofactor", None)
    if tf and tf.enabled:
        return redirect("accounts:security")
    if tf is None:
        tf = TwoFactor.objects.create(user=request.user, secret=twofa.new_secret())
    if request.method == "POST":
        if twofa.verify(tf.secret, request.POST.get("code", "")):
            codes = twofa.new_backup_codes()
            tf.enabled, tf.confirmed_at, tf.backup_hashes = True, timezone.now(), [twofa.hash_code(c) for c in codes]
            tf.save()
            audit.record(request, "2fa.enabled", request.user.username)
            return render(request, "accounts/twofa_codes.html", {"codes": codes, "page": "security"})
        messages.error(request, "That code is not right. Check the time on your phone and try again.")
    issuer = getattr(settings, "SITE_NAME", "EduPulse")
    return render(request, "accounts/twofa_setup.html", {"secret": tf.secret, "uri": twofa.uri(tf.secret, request.user.username, issuer), "page": "security"})


@login_required
@require_POST
def twofa_disable(request):
    from core import audit
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request, "Wrong password. Two-factor was not turned off.")
        return redirect("accounts:security")
    from django.conf import settings
    if request.user.role in getattr(settings, "REQUIRE_2FA_ROLES", ()):
        messages.error(request, "Your school requires two-factor for your role.")
        return redirect("accounts:security")
    from .models import TwoFactor
    TwoFactor.objects.filter(user=request.user).delete()
    audit.record(request, "2fa.disabled", request.user.username)
    messages.success(request, "Two-factor sign-in is off.")
    return redirect("accounts:security")
