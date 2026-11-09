from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.rbac import has_perm, perm_required
from core import audit
from core.notify import notify, notify_family

from . import services
from .forms import SettingsForm
from .models import Alert, EarlyWarningSettings, Intervention


@login_required
@perm_required("risk.view")
def index(request):
    status = request.GET.get("status", "active")
    level = request.GET.get("level", "")
    qs = services.alerts_for(request.user)
    qs = qs.filter(status="resolved") if status == "resolved" else qs.exclude(status="resolved")
    if level in dict(Alert.Level.choices):
        qs = qs.filter(level=level)
    rank = {"high": 0, "medium": 1, "watch": 2}
    rows = sorted(qs[:300], key=lambda a: (rank[a.level], -a.updated_at.timestamp()))
    return render(request, "risk/index.html", {"rows": rows, "status": status, "level": level, "levels": Alert.Level.choices,
                                              "can_scan": has_perm(request.user, "risk.configure"), "page": "risk"})


def _alert_for(user, pk):
    return get_object_or_404(services.alerts_for(user), pk=pk)


@login_required
@perm_required("risk.view")
def detail(request, pk):
    a = _alert_for(request.user, pk)
    if request.method == "POST":
        if not has_perm(request.user, "risk.manage"):
            raise PermissionDenied
        return _act(request, a)
    from academics.models import student_class
    from attendance.services import summary
    cls = student_class(a.student)
    staff = User.objects.filter(role__in=["teacher", "principal"], is_active=True)
    return render(request, "risk/detail.html", {
        "a": a, "student": a.student, "cls": cls, "window": EarlyWarningSettings.get().window_days,
        "att": summary(a.student, timezone.localdate() - timedelta(days=EarlyWarningSettings.get().window_days)),
        "tasks": a.tasks.select_related("assigned_to"), "staff": staff.order_by("first_name", "username"),
        "can_manage": has_perm(request.user, "risk.manage"), "history": Alert.objects.filter(student=a.student, status="resolved").exclude(pk=a.pk)[:5], "page": "risk"})


def _act(request, a):
    act = request.POST.get("action")
    me = request.user
    if a.status == Alert.Status.RESOLVED and act != "reopen_note":
        messages.error(request, "This alert is resolved.")
        return redirect("risk:detail", pk=a.pk)
    if act == "task":
        title = request.POST.get("title", "").strip()
        if not title:
            messages.error(request, "Give the task a title.")
        else:
            try:
                due = date.fromisoformat(request.POST.get("due_date", "")) if request.POST.get("due_date") else None
            except ValueError:
                due = None
            assignee = User.objects.filter(pk=request.POST.get("assigned_to") or 0, role__in=["teacher", "principal", "head_office", "super_admin"]).first()
            t = Intervention.objects.create(alert=a, title=title[:160], detail=request.POST.get("detail", "")[:400], assigned_to=assignee, due_date=due, created_by=me)
            if a.status == Alert.Status.OPEN:
                a.status = Alert.Status.IN_PROGRESS
                a.save()
            if assignee and assignee != me:
                notify(assignee, f"Follow-up task: {a.student.display_name}", t.title, f"/risk/{a.pk}/", "risk")
            audit.record(request, "risk.task", a.student.username, t.title)
            messages.success(request, "Task added.")
    elif act == "task_done":
        t = get_object_or_404(a.tasks, pk=request.POST.get("task"))
        t.status, t.outcome_note = Intervention.Status.DONE, request.POST.get("outcome", "")[:300]
        t.save()
        messages.success(request, "Task marked done.")
    elif act == "notify":
        msg = request.POST.get("message", "").strip()
        if not msg:
            messages.error(request, "Write a short message for the family first.")
        else:
            for p in a.student.parents.filter(is_active=True):
                notify(p, f"A note about {a.student.display_name}", msg[:300], f"/family/{a.student_id}/", "risk")
            audit.record(request, "risk.notify_parents", a.student.username, msg[:120])
            Intervention.objects.create(alert=a, title="Parents informed", detail=msg[:400], status="done", created_by=me, assigned_to=me)
            if a.status == Alert.Status.OPEN:
                a.status = Alert.Status.IN_PROGRESS
                a.save()
            messages.success(request, "Message sent to the parents.")
    elif act == "nuggets":
        from nuggets.engine import plan_for_student
        new = plan_for_student(a.student)
        Intervention.objects.create(alert=a, title="Remedial nuggets sent", detail=f"{len(new)} new nuggets assigned", status="done", created_by=me, assigned_to=me)
        if a.status == Alert.Status.OPEN:
            a.status = Alert.Status.IN_PROGRESS
            a.save()
        audit.record(request, "risk.nuggets", a.student.username, f"{len(new)} nuggets")
        messages.success(request, f"{len(new)} new nuggets assigned." if new else "No new nuggets were needed right now.")
    elif act == "resolve":
        note = request.POST.get("note", "").strip()
        if not note:
            messages.error(request, "Write a short note on what was done before resolving.")
        else:
            a.status, a.resolved_at, a.resolved_by, a.resolution_note = Alert.Status.RESOLVED, timezone.now(), me, note[:300]
            a.save()
            audit.record(request, "risk.resolve", a.student.username, note[:120])
            messages.success(request, "Alert resolved.")
    return redirect("risk:detail", pk=a.pk)


@login_required
@perm_required("risk.configure")
def settings_view(request):
    cfg = EarlyWarningSettings.get()
    form = SettingsForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request, "risk.settings", "early warning", str(form.cleaned_data))
        messages.success(request, "Thresholds saved. Run a scan to apply them.")
        return redirect("risk:settings")
    return render(request, "risk/settings.html", {"form": form, "page": "risk_settings"})


@login_required
@perm_required("risk.configure")
@require_POST
def run_scan(request):
    r = services.scan()
    audit.record(request, "risk.scan", "all students", str(r))
    messages.success(request, f"Scan done: {r['flagged']} students flagged ({r['created']} new, {r['updated']} updated, {r['resolved']} auto-closed).")
    return redirect("risk:index")
