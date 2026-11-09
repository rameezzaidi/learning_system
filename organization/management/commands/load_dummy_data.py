from django.core.management.base import BaseCommand

from accounts.models import User
from organization.mock import MockOracle
from organization.models import Campus, Region
from organization.services import SyncBusy, run_sync


class Command(BaseCommand):
    help = (
        "Load dummy Region / Campus / Student data through the real sync engine (no Oracle needed).\n"
        "  python manage.py load_dummy_data                  120 students\n"
        "  python manage.py load_dummy_data --students 500   more students\n"
        "  python manage.py load_dummy_data --round 2        simulate next day: moves, renames, leavers, new joiners\n"
        "  python manage.py load_dummy_data --reset          delete all Oracle-sourced data (before using real Oracle)"
    )

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=120)
        parser.add_argument("--round", type=int, default=1, choices=[1, 2])
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args, **o):
        if o["reset"]:
            users = User.objects.filter(student_profile__source="oracle")
            n = users.count()
            users.delete()
            Campus.objects.filter(source="oracle").delete()
            Region.objects.filter(source="oracle").delete()
            self.stdout.write(self.style.SUCCESS(f"Removed {n} Oracle-sourced students plus their campuses and regions."))
            return
        try:
            run = run_sync("command", MockOracle(o["students"], o["round"]))
        except SyncBusy as e:
            self.stdout.write(self.style.WARNING(str(e)))
            return
        s = run.stats
        self.stdout.write(self.style.SUCCESS(
            f"[{run.status}] regions +{s['regions_created']}  campuses +{s['campuses_created']}  "
            f"students +{s['students_created']} ~{s['students_updated']} -{s['students_deactivated']}"))
        for err in run.errors.splitlines()[:10]:
            self.stdout.write(self.style.WARNING("  " + err))
        self.stdout.write("Students sign in with their admission number (e.g. SOU-26-0001) and the default password.")
