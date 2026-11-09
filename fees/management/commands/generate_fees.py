from datetime import date

from django.core.management.base import BaseCommand, CommandError

from fees import services


class Command(BaseCommand):
    help = "Create this month's fee entries for every student (also catches up missed months). Schedule it daily; it is safe to repeat."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="YYYY-MM (default: current month)")
        parser.add_argument("--no-notify", action="store_true")

    def handle(self, *args, **o):
        month = None
        if o["month"]:
            try:
                y, m = o["month"].split("-")
                month = date(int(y), int(m), 1)
            except ValueError:
                raise CommandError("Use --month YYYY-MM")
        r = services.generate(month, notify=not o["no_notify"])
        self.stdout.write(self.style.SUCCESS(f"{r['entries']} fee entries created for {r['students']} students ({r['skipped']} skipped, month {r['month']:%B %Y})."))
