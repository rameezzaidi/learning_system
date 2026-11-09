from django.contrib import admin

from .models import Answer, Assessment, Attempt, Choice, Question

for m in (Assessment, Question, Choice, Attempt, Answer):
    admin.site.register(m)
