from django.contrib import admin

from .models import Course, Enrollment, Lesson, LessonProgress, SchoolClass, Subject

for m in (Subject, SchoolClass, Enrollment, Course, Lesson, LessonProgress):
    admin.site.register(m)
