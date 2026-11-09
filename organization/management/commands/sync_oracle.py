import time

from django.core.management.base import BaseCommand

from organization.models import SyncSettings
from organization.services import SyncBusy, run_sync


class Command(BaseCommand):
    help = (
        "Sync regions, campuses and students from Oracle.\n"
        "  python manage.py sync_oracle          run once (use with cron / Windows Task Scheduler)\n"
        "  python manage.py sync_oracle --loop   keep running; repeats every 'interval' minutes while\n"
        "                                        automatic sync is enabled in Oracle Sync settings"
    )

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Run forever on the configured interval.")
        parser.add_argument("--force", action="store_true", help="Run once even if automatic sync is disabled.")

    def _once(self, trigger):
        try:
            run = run_sync(trigger)
        except SyncBusy as e:
            self.stdout.write(self.style.WARNING(str(e)))
            return
        s = run.stats
        line = (f"[{run.status}] regions +{s['regions_created']}/~{s['regions_updated']}  "
                f"campuses +{s['campuses_created']}/~{s['campuses_updated']}  "
                f"students +{s['students_created']}/~{s['students_updated']}/-{s['students_deactivated']}")
        style = self.style.SUCCESS if run.status == "success" else self.style.WARNING
        self.stdout.write(style(line))
        for err in run.errors.splitlines()[:10]:
            self.stdout.write(self.style.ERROR("  " + err))

    def handle(self, *args, **opts):
        if not opts["loop"]:
            if not opts["force"] and not SyncSettings.load().enabled:
                self.stdout.write("Automatic sync is disabled in Oracle Sync settings. Use --force to run anyway.")
                return
            self._once("command")
            return
        self.stdout.write("Sync loop started. Press Ctrl+C to stop.")
        while True:
            cfg = SyncSettings.load()
            if cfg.enabled:
                self._once("auto")
            time.sleep(max(cfg.interval_minutes, 5) * 60)
