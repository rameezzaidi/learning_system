from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User

from .forms import ClassForm, CourseForm, EnrollForm, HelpForm, LessonForm, SubjectForm
from .models import (
    Course, Enrollment, Lesson, LessonProgress, Module, SchoolClass, Subject, course_outline, course_rows,
    first_item, next_item, progress_for, student_class,
)

ADMIN = "super_admin"


# ---------- access helpers ----------

def can_manage(user, course):
    return user.is_super_admin or (user.is_teacher and course.teacher_id == user.id)


def can_view(user, course):
    if can_manage(user, course):
        return True
    if user.is_student:
        return Enrollment.objects.filter(student=user, school_class_id=course.school_class_id).exists()
    return False


# ---------- Classes (super admin) ----------

@login_required
@role_required(ADMIN)
def class_list(request):
    classes = SchoolClass.objects.annotate(
        n_students=Count("enrollments", distinct=True), n_courses=Count("courses", distinct=True)
    )
    return render(request, "academics/class_list.html", {"classes": classes, "page": "classes"})


@login_required
@role_required(ADMIN)
def class_form(request, pk=None):
    obj = get_object_or_404(SchoolClass, pk=pk) if pk else None
    form = ClassForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"{saved} saved.")
        return redirect("academics:class_detail", pk=saved.pk)
    return render(request, "academics/form.html", {
        "form": form, "page": "classes", "title": "Edit class" if obj else "New class",
        "back": "academics:class_list",
    })


@login_required
@role_required(ADMIN)
def class_detail(request, pk):
    cls = get_object_or_404(SchoolClass, pk=pk)
    courses = cls.courses.select_related("subject", "teacher").annotate(n_lessons=Count("lessons"))
    students = User.objects.filter(enrollment__school_class=cls).order_by("first_name", "username")
    return render(request, "academics/class_detail.html", {
        "cls": cls, "courses": courses, "students": students,
        "enroll_form": EnrollForm(cls), "page": "classes",
    })


@login_required
@role_required(ADMIN)
@require_POST
def class_delete(request, pk):
    cls = get_object_or_404(SchoolClass, pk=pk)
    name = str(cls)
    cls.delete()
    messages.success(request, f"{name} deleted.")
    return redirect("academics:class_list")


@login_required
@role_required(ADMIN)
@require_POST
def enroll(request, pk):
    cls = get_object_or_404(SchoolClass, pk=pk)
    form = EnrollForm(cls, request.POST)
    if form.is_valid():
        students = form.cleaned_data["students"]
        for s in students:
            Enrollment.objects.update_or_create(student=s, defaults={"school_class": cls})
        messages.success(request, f"{len(students)} student(s) added to {cls}.")
    else:
        messages.error(request, "Please select at least one student.")
    return redirect("academics:class_detail", pk=cls.pk)


@login_required
@role_required(ADMIN)
@require_POST
def unenroll(request, pk, student_pk):
    Enrollment.objects.filter(student_id=student_pk, school_class_id=pk).delete()
    messages.success(request, "Student removed from the class.")
    return redirect("academics:class_detail", pk=pk)


# ---------- Subjects ----------

@login_required
@role_required(ADMIN)
def subject_list(request):
    form = SubjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Subject added.")
        return redirect("academics:subject_list")
    subjects = Subject.objects.annotate(n_courses=Count("courses"))
    return render(request, "academics/subject_list.html", {"subjects": subjects, "form": form, "page": "subjects"})


@login_required
@role_required(ADMIN)
@require_POST
def subject_delete(request, pk):
    get_object_or_404(Subject, pk=pk).delete()
    messages.success(request, "Subject deleted.")
    return redirect("academics:subject_list")


# ---------- Courses ----------

@login_required
@role_required(ADMIN)
def course_form(request, class_pk=None, pk=None):
    obj = get_object_or_404(Course, pk=pk) if pk else None
    cls = obj.school_class if obj else get_object_or_404(SchoolClass, pk=class_pk)
    form = CourseForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        course = form.save(commit=False)
        course.school_class = cls
        clash = Course.objects.filter(school_class=cls, subject=course.subject).exclude(pk=course.pk).exists()
        if clash:
            form.add_error("subject", "This subject is already added to the class.")
        else:
            course.save()
            messages.success(request, f"{course.subject} added to {cls}." if not obj else "Course updated.")
            return redirect("academics:class_detail", pk=cls.pk)
    return render(request, "academics/form.html", {
        "form": form, "page": "classes", "title": f"{'Edit' if obj else 'Add'} subject · {cls}",
        "back": "academics:class_detail", "back_arg": cls.pk,
    })


@login_required
@role_required(ADMIN)
@require_POST
def course_delete(request, pk):
    course = get_object_or_404(Course, pk=pk)
    cls_pk = course.school_class_id
    course.delete()
    messages.success(request, "Course removed from the class.")
    return redirect("academics:class_detail", pk=cls_pk)


@login_required
def my_courses(request):
    user = request.user
    if user.is_teacher:
        courses = Course.objects.filter(teacher=user).select_related("subject", "school_class").annotate(
            n_lessons=Count("lessons", distinct=True), n_modules=Count("modules", distinct=True)
        )
        return render(request, "academics/my_courses.html", {"courses": courses, "page": "courses"})
    if user.is_student:
        cls = student_class(user)
        courses = cls.courses.select_related("subject", "teacher") if cls else Course.objects.none()
        rows = []
        for c in courses:
            outline = course_outline(c, user)
            p = progress_for(user, c)
            nxt = next_item(outline)
            rows.append({"course": c, **p, "n_modules": len(outline), "continue": nxt or first_item(outline),
                         "finished": p["total"] > 0 and p["done"] == p["total"]})
        return render(request, "academics/my_courses.html", {"rows": rows, "cls": cls, "page": "courses"})
    return redirect("accounts:dashboard")


@login_required
def course_detail(request, pk):
    course = get_object_or_404(Course.objects.select_related("subject", "school_class", "teacher"), pk=pk)
    if not can_view(request.user, course):
        raise PermissionDenied
    manage = can_manage(request.user, course)
    from assessments.models import Assessment
    ctx = {"course": course, "manage": manage, "page": "courses" if not request.user.is_super_admin else "classes"}
    if manage:
        ctx["outline"] = course_outline(course, manage=True)
        ctx["assessments"] = course.assessments.all()
        students = User.objects.filter(enrollment__school_class=course.school_class).order_by("first_name", "username")
        ctx["student_rows"] = [{"student": s, **progress_for(s, course)} for s in students]
        ctx["open_help"] = course.help_requests.filter(status="open").count()
        return render(request, "academics/course_manage.html", ctx)
    outline = course_outline(course, request.user)
    ctx.update(outline=outline, progress=progress_for(request.user, course),
               continue_item=next_item(outline) or first_item(outline), started=any(i["done"] for m in outline for i in m["items"]),
               assessments=course.assessments.filter(is_published=True),
               minutes=sum(i["lesson"].minutes for m in outline for i in m["items"]),
               n_items=sum(m["total"] for m in outline),
               help_form=HelpForm())
    return render(request, "academics/course_student.html", ctx)


# ---------- Lessons ----------

@login_required
def lesson_form(request, course_pk=None, pk=None):
    obj = get_object_or_404(Lesson, pk=pk) if pk else None
    course = obj.course if obj else get_object_or_404(Course, pk=course_pk)
    if not can_manage(request.user, course):
        raise PermissionDenied
    form = LessonForm(request.POST or None, request.FILES or None, instance=obj, course=course,
                      initial={"module": request.GET.get("module")} if not obj else None)
    if request.method == "POST" and form.is_valid():
        lesson = form.save(commit=False)
        lesson.course = course
        lesson.save()
        messages.success(request, "Lesson saved.")
        return redirect("academics:course_detail", pk=course.pk)
    return render(request, "academics/lesson_form.html", {
        "form": form, "course": course, "title": "Edit learning item" if obj else "New learning item",
        "page": "courses" if not request.user.is_super_admin else "classes",
    })


@login_required
@require_POST
def lesson_delete(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    if not can_manage(request.user, lesson.course):
        raise PermissionDenied
    course_pk = lesson.course_id
    lesson.delete()
    messages.success(request, "Lesson deleted.")
    return redirect("academics:course_detail", pk=course_pk)


def _completes_on_open(lesson):
    """Items that count as done as soon as the student opens them.

    Games, quizzes and YouTube videos complete when the student actually finishes them instead.
    """
    from core.templatetags.ui import embed
    K = Lesson.Kind
    if lesson.kind in (K.GAME, K.QUIZ):
        return False
    if lesson.kind == K.VIDEO:
        return not embed(lesson.url)  # non-YouTube video: cannot be tracked, so opening counts
    return True


@login_required
def lesson_view(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related("course__subject", "course__school_class", "module", "assessment"), pk=pk)
    course = lesson.course
    if not can_view(request.user, course):
        raise PermissionDenied
    manage = can_manage(request.user, course)
    if not manage and not (lesson.is_published and (lesson.module is None or lesson.module.is_published)):
        raise PermissionDenied
    student = request.user if request.user.is_student else None
    if student and lesson.is_published and _completes_on_open(lesson):
        LessonProgress.objects.get_or_create(student=student, lesson=lesson)  # zero-click completion
    done = bool(student) and LessonProgress.objects.filter(student=student, lesson=lesson).exists()
    outline = course_outline(course, student, manage=manage)
    flat = [i["lesson"] for m in outline for i in m["items"]]
    idx = next((i for i, l in enumerate(flat) if l.pk == lesson.pk), None)
    ctx = {
        "lesson": lesson, "course": course, "done": done, "manage": manage, "outline": outline,
        "prev": flat[idx - 1] if idx else None,
        "next": flat[idx + 1] if idx is not None and idx + 1 < len(flat) else None,
        "pos": (idx or 0) + 1, "n_items": len(flat),
        "progress": progress_for(student, course) if student else None,
        "page": "courses" if not request.user.is_super_admin else "classes",
    }
    if lesson.kind == Lesson.Kind.GAME:
        ctx["game"] = {"type": lesson.game_type, "items": lesson.game_pairs()}
    if lesson.kind == Lesson.Kind.QUIZ and lesson.assessment and student:
        from assessments.grading import attempts_left, best_attempt
        a = lesson.assessment
        ctx.update(quiz=a, quiz_best=best_attempt(a, student), quiz_left=attempts_left(a, student),
                   quiz_open=a.is_published and not a.is_past_due)
    if student:
        ctx["help_form"] = HelpForm()
        ctx["my_help"] = lesson.help_requests.filter(student=student)
    return render(request, "academics/lesson_view.html", ctx)


@login_required
@role_required("student")
@require_POST
def item_done(request, pk):
    """Called by the browser when a student finishes a game or watches a video (no button involved)."""
    from django.http import JsonResponse
    lesson = get_object_or_404(Lesson, pk=pk, is_published=True, kind__in=[Lesson.Kind.GAME, Lesson.Kind.VIDEO])
    if not can_view(request.user, lesson.course):
        raise PermissionDenied
    LessonProgress.objects.get_or_create(student=request.user, lesson=lesson)
    return JsonResponse({"ok": True, "progress": progress_for(request.user, lesson.course)})


# ---------- Parent view ----------

@login_required
def child_progress(request, student_pk):
    student = get_object_or_404(User, pk=student_pk, role=User.Role.STUDENT)
    allowed = request.user.is_super_admin or (request.user.is_parent and request.user.children.filter(pk=student.pk).exists())
    if not allowed:
        raise PermissionDenied
    cls = student_class(student)
    courses = cls.courses.select_related("subject", "teacher") if cls else Course.objects.none()
    done_ids = set(LessonProgress.objects.filter(student=student).values_list("lesson_id", flat=True))
    rows = []
    for c in courses:
        rows.append({"course": c, **progress_for(student, c),
                     "lessons": [{"lesson": l, "done": l.id in done_ids} for l in c.published_lessons()]})
    from assessments.grading import student_summary
    summary = student_summary(student, courses)
    avgs = [x["avg"] for x in summary if x["avg"] is not None]
    return render(request, "academics/child_progress.html", {
        "summary": summary, "overall": round(sum(avgs) / len(avgs), 1) if avgs else None,
        "student": student, "cls": cls, "rows": rows, "page": "child", "active_child": student.pk,
    })
