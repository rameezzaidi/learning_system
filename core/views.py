from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from accounts.decorators import role_required

from .forms import SchoolSettingsForm
from .models import SchoolSettings


@login_required
@role_required("super_admin")
def school_settings(request):
    obj = SchoolSettings.load()
    form = SchoolSettingsForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "School appearance saved. Everyone now sees the new look.")
        return redirect("core:settings")
    return render(request, "core/settings.html", {"form": form, "page": "settings"})


# ---------------------------------------------------------------- permission matrix & audit log
from accounts import rbac  # noqa: E402
from accounts.models import RolePermission, User  # noqa: E402

from . import audit  # noqa: E402
from .models import AuditLog  # noqa: E402


@login_required
@role_required("super_admin")
def permissions(request):
    roles = rbac.ROLES_EDITABLE
    labels = dict(User.Role.choices)
    if request.method == "POST":
        changes = []
        for role in roles:
            for code in rbac.ALL:
                want = request.POST.get(f"{role}|{code}") == "on"
                default = code in rbac.DEFAULTS.get(role, set())
                if want == default:
                    RolePermission.objects.filter(role=role, code=code).delete()
                else:
                    _, created = RolePermission.objects.update_or_create(role=role, code=code, defaults={"allowed": want})
                    changes.append(f"{role}:{code}={'on' if want else 'off'}")
        audit.record(request, "rbac.update", "permission matrix", "; ".join(changes)[:380] or "reset to defaults")
        messages.success(request, "Permissions saved. They apply immediately.")
        return redirect("core:permissions")
    matrix = rbac.role_matrix()
    groups = [{"module": m, "items": [{"code": c, "label": l, "cells": [(r, matrix[r][c], c in rbac.DEFAULTS.get(r, set())) for r in roles]} for c, l in items]}
              for m, items in rbac.MODULES]
    return render(request, "core/permissions.html", {"groups": groups, "roles": [(r, labels.get(r, r)) for r in roles], "page": "perms"})


@login_required
def audit_log(request):
    if not rbac.has_perm(request.user, "audit.view"):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    qs = AuditLog.objects.select_related("user")
    action, who = request.GET.get("action", "").strip(), request.GET.get("q", "").strip()
    if action:
        qs = qs.filter(action__startswith=action)
    if who:
        qs = qs.filter(username__icontains=who)
    from django.core.paginator import Paginator
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    actions = sorted(AuditLog.objects.values_list("action", flat=True).distinct())
    return render(request, "core/audit.html", {"page_obj": page, "actions": actions, "action": action, "q": who, "page": "audit"})
