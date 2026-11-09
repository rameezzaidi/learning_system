from django.core.management.base import BaseCommand

from risk import services


class Command(BaseCommand):
    help = "Scan for early-warning signs and raise/refresh alerts. Safe to run daily (idempotent)."

    def handle(self, *a, **o):
        r = services.scan()
        self.stdout.write(self.style.SUCCESS(f"Flagged {r['flagged']} (new {r['created']}, updated {r['updated']}, auto-closed {r['resolved']})"))
