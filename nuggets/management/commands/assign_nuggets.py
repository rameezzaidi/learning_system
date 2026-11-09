from django.core.management.base import BaseCommand

from exams.models import Exam
from nuggets import engine


class Command(BaseCommand):
    help = "Send nuggets to students who are weak in published exams (run daily from a scheduler)."

    def add_arguments(self, parser):
        parser.add_argument("--exam", type=int, help="Only this exam id (default: every published exam)")

    def handle(self, *a, **o):
        exams = Exam.objects.filter(is_published=True)
        if o.get("exam"):
            exams = exams.filter(pk=o["exam"])
        for e in exams:
            s = engine.assign_for_exam(e)
            self.stdout.write(f"{e.name}: {s['assigned']} nuggets to {s['students']} students ({s['created']} created)")
