from django.contrib import admin

from .models import AISuggestion, Exam, ExamPaper, GradeBand, Mark

admin.site.register(GradeBand)
admin.site.register(Exam)
admin.site.register(ExamPaper)
admin.site.register(Mark)
admin.site.register(AISuggestion)
