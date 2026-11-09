"""Student ↔ teacher help desk."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import role_required

from .forms import HelpForm, ReplyForm
from .models import Course, HelpMessage, HelpRequest, Lesson
from .views import can_manage, can_view

FILTERS = {"open": "open", "answered": "answered", "resolved": "resolved"}


def _requests_for(user):
    qs = HelpRequest.objects.select_related("course__subject", "course__school_class", "student", "lesson")
    if user.is_super_admin:
        return qs
    if user.is_teacher:
        return qs.filter(course__teacher=user)
    if user.is_student:
        return qs.filter(student=user)
    raise PermissionDenied


@login_required
@role_required("student")
@require_POST
def help_ask(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk)
    if not can_view(request.user, course):
        raise PermissionDenied
    form = HelpForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please write your question.")
        return redirect("academics:course_detail", pk=course.pk)
    lesson = None
    lid = request.POST.get("lesson")
    if lid and lid.isdigit():
        lesson = Lesson.objects.filter(pk=lid, course=course).first()
    body = form.cleaned_data["body"].strip()
    subject = form.cleaned_data["subject"].strip() or (f"About: {lesson.title}" if lesson else body[:60])
    req = HelpRequest.objects.create(course=course, lesson=lesson, student=request.user, subject=subject[:200])
    HelpMessage.objects.create(request=req, author=request.user, body=body)
    messages.success(request, "Your question was sent to the teacher.")
    return redirect("academics:help_thread", pk=req.pk)


@login_required
def help_list(request):
    qs = _requests_for(request.user)
    status = request.GET.get("status", "")
    shown = qs.filter(status=FILTERS[status]) if status in FILTERS else qs
    counts = {k: qs.filter(status=v).count() for k, v in FILTERS.items()}
    return render(request, "academics/help_list.html", {
        "items": shown, "status": status, "counts": counts, "page": "help", "total": qs.count()})


@login_required
def help_thread(request, pk):
    req = get_object_or_404(HelpRequest.objects.select_related("course__subject", "course__school_class", "student", "lesson"), pk=pk)
    user = request.user
    manage = can_manage(user, req.course)
    if not (manage or req.student_id == user.id):
        raise PermissionDenied
    form = ReplyForm(request.POST or None)
    if request.method == "POST":
        if "resolve" in request.POST:
            req.status = HelpRequest.Status.RESOLVED
            req.save()
            messages.success(request, "Marked as resolved.")
            return redirect("academics:help_thread", pk=req.pk)
        if form.is_valid():
            HelpMessage.objects.create(request=req, author=user, body=form.cleaned_data["body"].strip())
            req.status = HelpRequest.Status.ANSWERED if manage else HelpRequest.Status.OPEN
            req.save()
            messages.success(request, "Reply sent.")
            return redirect("academics:help_thread", pk=req.pk)
    return render(request, "academics/help_thread.html", {
        "req": req, "msgs": req.messages.select_related("author"), "form": ReplyForm(), "manage": manage, "page": "help"})
