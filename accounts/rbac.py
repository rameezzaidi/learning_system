"""Granular permissions: module.action codes, role defaults, and Super Admin overrides.

Super Admin always has every permission. For other roles the effective value is the database
override (RolePermission) if one exists, otherwise the default below. *What data* a permission
applies to is decided separately by core.scope (campus / region).
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

R = "super_admin teacher student parent head_office regional_director principal".split()

# (code, label) grouped by module
MODULES = [
    ("Students", [
        ("students.view", "View student list and profiles"),
        ("students.create", "Add students"),
        ("students.edit", "Edit students"),
        ("students.export", "Export student data (CSV)"),
    ]),
    ("Campuses & regions", [
        ("campuses.view", "View campus overview and comparison"),
        ("campuses.manage", "Create / edit regions and campuses"),
    ]),
    ("Reports", [
        ("reports.view", "View performance reports"),
        ("reports.export", "Export reports (CSV)"),
    ]),
    ("Learning", [
        ("nuggets.insights", "View nugget insights"),
        ("nuggets.review", "Approve / reject AI nuggets"),
    ]),
    ("Curriculum & handover", [
        ("curriculum.monitor", "Monitor curriculum coverage across campuses"),
        ("handover.view", "View teacher handovers in scope"),
        ("handover.create", "Create handovers for any course in scope"),
    ]),
    ("Attendance & early warning", [
        ("attendance.view", "View attendance reports in scope"),
        ("attendance.mark", "Mark student and teacher attendance"),
        ("attendance.leave_decide", "Approve or reject leave requests"),
        ("risk.view", "View early-warning alerts in scope"),
        ("risk.manage", "Work on alerts: plans, tasks, notify parents, resolve"),
        ("risk.configure", "Change risk thresholds and run scans"),
    ]),
    ("Timetable & calendar", [
        ("timetable.view", "View timetables in scope"),
        ("timetable.manage", "Edit timetables, bell schedule and substitutions"),
        ("calendar.manage", "Add holidays, events and terms"),
    ]),
    ("Student information (SIS)", [
        ("sis.view", "View admissions, student documents and certificates"),
        ("sis.manage", "Manage admissions, documents, promotion and transfer certificates"),
    ]),
    ("Question bank", [
        ("bank.manage", "Manage the question bank and generate papers"),
    ]),
    ("Insights & operations", [
        ("bi.view", "View the executive dashboard"),
        ("library.manage", "Manage the library: books, issue and return"),
        ("transport.manage", "Manage transport routes and assignments"),
        ("transport.view", "View transport routes in scope"),
    ]),
    ("Fees", [
        ("fees.view", "View fee dashboard and ledgers in scope"),
        ("fees.collect", "Record payments"),
        ("fees.manage", "Set fee plans, add charges/discounts, void entries, generate fees"),
    ]),
    ("Examinations", [
        ("exams.publish", "Publish results"),
    ]),
    ("Administration", [
        ("users.manage", "Create and edit users"),
        ("audit.view", "View audit log"),
        ("rbac.manage", "Change the permission matrix"),
    ]),
]
LABELS = {c: l for _, items in MODULES for c, l in items}
ALL = list(LABELS)

_MGMT = {"bi.view", "transport.view", "sis.view", "timetable.view", "attendance.view", "risk.view", "students.view", "campuses.view", "reports.view", "reports.export", "students.export", "curriculum.monitor", "handover.view"}
DEFAULTS = {
    "teacher": {"bank.manage", "nuggets.insights", "nuggets.review", "attendance.mark", "attendance.leave_decide", "risk.view", "risk.manage"},
    "student": set(),
    "parent": set(),
    "head_office": _MGMT | {"bank.manage", "library.manage", "transport.manage", "sis.manage", "timetable.manage", "calendar.manage", "risk.manage", "risk.configure", "fees.view", "fees.manage", "students.create", "students.edit", "audit.view", "nuggets.insights", "handover.create"},
    "regional_director": _MGMT | {"fees.view"},
    "principal": _MGMT | {"bank.manage", "library.manage", "transport.manage", "sis.manage", "timetable.manage", "calendar.manage", "attendance.mark", "attendance.leave_decide", "risk.manage", "risk.configure", "fees.view", "fees.collect", "students.create", "students.edit", "nuggets.insights", "handover.create"},
}
ROLES_EDITABLE = ["head_office", "regional_director", "principal", "teacher", "parent", "student"]


def _overrides():
    from .models import RolePermission
    return {(r.role, r.code): r.allowed for r in RolePermission.objects.all()}


def role_matrix():
    """{role: {code: bool}} with overrides applied, for the editor UI."""
    ov = _overrides()
    return {role: {c: ov.get((role, c), c in DEFAULTS.get(role, set())) for c in ALL} for role in ROLES_EDITABLE}


def has_perm(user, code):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.role == "super_admin":
        return True
    cache = getattr(user, "_rbac", None)
    if cache is None:
        ov = {(r, c): a for (r, c), a in _overrides().items() if r == user.role}
        cache = user._rbac = {c: ov.get((user.role, c), c in DEFAULTS.get(user.role, set())) for c in ALL}
    return bool(cache.get(code))


def perm_required(*codes):
    """Allow if the user has ANY of `codes`. Use below @login_required."""

    def deco(view):
        @wraps(view)
        def wrapper(request, *a, **k):
            if not any(has_perm(request.user, c) for c in codes):
                raise PermissionDenied
            return view(request, *a, **k)
        return wrapper
    return deco
