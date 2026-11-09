"""Teacher tools: modules, ordering and publishing of learning items."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ModuleForm
from .models import Course, Lesson, Module
from .views import can_manage


def _course_for_manage(user, course):
    if not can_manage(user, course):
        raise PermissionDenied
    return course


@login_required
def module_form(request, course_pk=None, pk=None):
    obj = get_object_or_404(Module, pk=pk) if pk else None
    course = obj.course if obj else get_object_or_404(Course, pk=course_pk)
    _course_for_manage(request.user, course)
    form = ModuleForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        m = form.save(commit=False)
        m.course = course
        m.save()
        messages.success(request, "Module saved.")
        return redirect("academics:course_detail", pk=course.pk)
    return render(request, "academics/form.html", {
        "form": form, "title": "Edit module" if obj else "New module", "page": "courses",
        "back": "academics:course_detail", "back_arg": course.pk})


@login_required
@require_POST
def module_delete(request, pk):
    m = get_object_or_404(Module, pk=pk)
    _course_for_manage(request.user, m.course)
    course = m.course
    n = m.items.count()
    m.delete()
    messages.success(request, f"Module deleted{f' with {n} item(s)' if n else ''}.")
    return redirect("academics:course_detail", pk=course.pk)


def _swap(queryset, obj, direction):
    if direction not in ("up", "down"):
        return
    items = list(queryset)
    i = next((k for k, x in enumerate(items) if x.pk == obj.pk), None)
    j = None if i is None else (i - 1 if direction == "up" else i + 1)
    if j is None or j < 0 or j >= len(items):
        return
    items[i], items[j] = items[j], items[i]
    for pos, x in enumerate(items, start=1):  # renumber so positions are always 1..n
        if x.position != pos:
            type(x).objects.filter(pk=x.pk).update(position=pos)


@login_required
@require_POST
def module_move(request, pk, direction):
    m = get_object_or_404(Module, pk=pk)
    _course_for_manage(request.user, m.course)
    _swap(Module.objects.filter(course=m.course), m, direction)
    return redirect("academics:course_detail", pk=m.course_id)


@login_required
@require_POST
def module_toggle(request, pk):
    m = get_object_or_404(Module, pk=pk)
    _course_for_manage(request.user, m.course)
    m.is_published = not m.is_published
    m.save(update_fields=["is_published"])
    return redirect("academics:course_detail", pk=m.course_id)


@login_required
@require_POST
def lesson_move(request, pk, direction):
    l = get_object_or_404(Lesson, pk=pk)
    _course_for_manage(request.user, l.course)
    _swap(Lesson.objects.filter(module=l.module).order_by("position", "id"), l, direction)
    return redirect("academics:course_detail", pk=l.course_id)


@login_required
@require_POST
def lesson_toggle(request, pk):
    l = get_object_or_404(Lesson, pk=pk)
    _course_for_manage(request.user, l.course)
    l.is_published = not l.is_published
    l.save(update_fields=["is_published"])
    return redirect("academics:course_detail", pk=l.course_id)
