from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Campus, Region, StudentProfile, SyncRun, SyncSettings, validate_readonly_sql
from .services import SyncBusy, run_sync


class FakeOracle:
    def __init__(self, regions, campuses, students):
        self.data = {"regions": regions, "campuses": campuses, "students": students}

    def fetch(self, sql):
        for k, rows in self.data.items():
            if f"FROM {k.upper()}" in sql.upper():
                return rows
        raise AssertionError("unexpected sql " + sql)


REGIONS = [{"external_id": 1, "name": "North", "code": "N"}, {"external_id": 2, "name": "South", "code": "S"}]
CAMPUSES = [
    {"external_id": 10, "region_id": 1, "name": "North Main", "code": "NM"},
    {"external_id": 20, "region_id": 2, "name": "South Main", "code": "SM"},
]
STUDENTS = [
    {"external_id": 100, "admission_no": "A-100", "first_name": "Ali", "last_name": "Raza", "email": "a@x.com", "phone": "1", "campus_id": 10},
    {"external_id": 101, "admission_no": "A-101", "first_name": "Sana", "last_name": "Khan", "email": "", "phone": "", "campus_id": 20},
]


def feed(**over):
    d = {"regions": REGIONS, "campuses": CAMPUSES, "students": STUDENTS}
    d.update(over)
    return FakeOracle(d["regions"], d["campuses"], d["students"])


class SyncEngineTests(TestCase):
    def test_first_sync_creates_everything(self):
        run = run_sync("manual", feed())
        self.assertEqual(run.status, "success", run.errors)
        self.assertEqual(Region.objects.filter(source="oracle").count(), 2)
        self.assertEqual(Campus.objects.get(external_id="10").region.name, "North")
        u = User.objects.get(username="A-100")
        self.assertEqual((u.role, u.first_name, u.student_profile.campus.name), ("student", "Ali", "North Main"))
        self.assertTrue(u.check_password("Student@123"))
        self.assertEqual(run.stats["students_created"], 2)

    def test_second_sync_is_idempotent_and_updates(self):
        run_sync("manual", feed())
        changed = [dict(STUDENTS[0], first_name="Alee", campus_id=20), STUDENTS[1]]
        run = run_sync("auto", feed(students=changed))
        self.assertEqual(User.objects.filter(role="student").count(), 2)
        self.assertEqual((run.stats["students_created"], run.stats["students_updated"]), (0, 2))
        u = User.objects.get(username="A-100")
        self.assertEqual((u.first_name, u.student_profile.campus.external_id), ("Alee", "20"))

    def test_manual_records_are_never_touched(self):
        reg = Region.objects.create(name="Manual Region")
        manual = User.objects.create_user("man1", password="x", role="student")
        StudentProfile.objects.create(user=manual, source="manual")
        run_sync("manual", feed(regions=[], campuses=[], students=[]))
        manual.refresh_from_db()
        self.assertTrue(manual.is_active)
        self.assertTrue(Region.objects.get(pk=reg.pk).is_active)

    def test_missing_students_deactivated_and_reactivated(self):
        run_sync("manual", feed())
        run = run_sync("manual", feed(students=[STUDENTS[0]]))
        self.assertEqual(run.stats["students_deactivated"], 1)
        self.assertFalse(User.objects.get(username="A-101").is_active)
        run_sync("manual", feed())
        self.assertTrue(User.objects.get(username="A-101").is_active)

    def test_empty_feed_does_not_wipe_data(self):
        run_sync("manual", feed())
        run = run_sync("manual", feed(regions=[], campuses=[], students=[]))
        self.assertEqual(run.status, "partial")
        self.assertEqual(User.objects.filter(role="student", is_active=True).count(), 2)
        self.assertTrue(Region.objects.filter(is_active=True).count() == 2)

    def test_deactivate_missing_can_be_switched_off(self):
        s = SyncSettings.load(); s.deactivate_missing = False; s.save()
        run_sync("manual", feed())
        run_sync("manual", feed(students=[STUDENTS[0]]))
        self.assertTrue(User.objects.get(username="A-101").is_active)

    def test_bad_rows_reported_but_good_rows_saved(self):
        bad_students = STUDENTS + [{"external_id": 102, "first_name": "Zed", "campus_id": 999}, {"external_id": "", "first_name": ""}]
        run = run_sync("manual", feed(students=bad_students))
        self.assertEqual(run.status, "partial")
        self.assertEqual(run.stats["students_created"], 2)
        self.assertIn("unknown campus", run.errors)

    def test_campus_with_unknown_region_skipped(self):
        run = run_sync("manual", feed(campuses=CAMPUSES + [{"external_id": 30, "region_id": 77, "name": "Ghost"}]))
        self.assertEqual(run.status, "partial")
        self.assertFalse(Campus.objects.filter(name="Ghost").exists())

    def test_username_collision_gets_suffix(self):
        User.objects.create_user("A-100", password="x", role="teacher")
        run_sync("manual", feed())
        self.assertTrue(User.objects.filter(username="A-100-100").exists())

    def test_connector_failure_is_logged(self):
        class Boom:
            def fetch(self, sql):
                raise ConnectionError("ORA-12541: no listener")
        run = run_sync("manual", Boom())
        self.assertEqual(run.status, "failed")
        self.assertIn("no listener", run.errors)

    def test_unconfigured_oracle_fails_cleanly(self):
        run = run_sync("manual")
        self.assertEqual(run.status, "failed")
        self.assertIn("not configured", run.errors)

    def test_cannot_run_twice_at_once(self):
        SyncRun.objects.create(status="running")
        with self.assertRaises(SyncBusy):
            run_sync("manual", feed())

    def test_sql_validation(self):
        validate_readonly_sql("SELECT a FROM b;")
        validate_readonly_sql("WITH x AS (SELECT 1 FROM dual) SELECT * FROM x")
        for bad in ("DELETE FROM students", "SELECT 1 FROM dual; DROP TABLE x", "UPDATE t SET a=1", "SELECT * FROM t WHERE 1=1 AND x IN (SELECT 1 FROM dual) -- ok"):
            if "--" in bad:
                continue
            with self.assertRaises(ValidationError):
                validate_readonly_sql(bad)
        # column names that merely contain a keyword are fine
        validate_readonly_sql("SELECT created_at, last_update FROM t")

    def test_unsafe_sql_in_settings_blocks_run(self):
        SyncSettings.objects.update_or_create(pk=1, defaults={})
        SyncSettings.objects.filter(pk=1).update(sql_students="DELETE FROM students")
        run = run_sync("manual", feed())
        self.assertEqual(run.status, "failed")


class OrganizationViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@x.com", "pw12345")
        self.teacher = User.objects.create_user("t1", password="pw12345", role="teacher")
        self.client.login(username="admin", password="pw12345")
        run_sync("manual", feed())

    def test_pages_open_for_admin(self):
        for name in ("overview", "student_list", "sync", "student_create", "region_create", "campus_create"):
            self.assertEqual(self.client.get(reverse(f"organization:{name}")).status_code, 200, name)

    def test_other_roles_blocked(self):
        self.client.logout(); self.client.login(username="t1", password="pw12345")
        for name in ("overview", "student_list", "sync"):
            self.assertEqual(self.client.get(reverse(f"organization:{name}")).status_code, 403, name)

    def test_manual_student_add_edit(self):
        campus = Campus.objects.get(external_id="10")
        r = self.client.post(reverse("organization:student_create"), {
            "first_name": "Manual", "last_name": "One", "username": "m1", "admission_no": "M-1",
            "campus": campus.pk, "password": "secret99", "email": "", "phone": "",
        })
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username="m1")
        self.assertEqual((u.student_profile.source, u.student_profile.campus_id), ("manual", campus.pk))
        self.assertTrue(u.check_password("secret99"))
        # duplicate username rejected
        r = self.client.post(reverse("organization:student_create"), {
            "first_name": "X", "username": "m1", "password": "secret99"})
        self.assertEqual(r.status_code, 200)
        # edit
        r = self.client.post(reverse("organization:student_edit", args=[u.pk]), {
            "first_name": "Manual", "last_name": "Two", "username": "m1", "admission_no": "M-1",
            "campus": "", "password": "", "email": "", "phone": ""})
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertEqual(u.last_name, "Two")
        self.assertIsNone(u.student_profile.campus)
        self.assertTrue(u.check_password("secret99"))

    def test_oracle_student_cannot_be_edited(self):
        u = User.objects.get(username="A-100")
        r = self.client.get(reverse("organization:student_edit", args=[u.pk]))
        self.assertEqual(r.status_code, 302)

    def test_oracle_region_campus_protected_manual_ok(self):
        oreg = Region.objects.get(external_id="1")
        self.client.post(reverse("organization:region_delete", args=[oreg.pk]))
        self.assertTrue(Region.objects.filter(pk=oreg.pk).exists())
        self.assertEqual(self.client.get(reverse("organization:region_edit", args=[oreg.pk])).status_code, 302)
        # manual region + campus flow
        r = self.client.post(reverse("organization:region_create"), {"name": "East", "code": "E", "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        east = Region.objects.get(name="East")
        r = self.client.post(reverse("organization:campus_create"), {"region": east.pk, "name": "East Campus", "code": "", "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        # region with campuses cannot be deleted
        self.client.post(reverse("organization:region_delete", args=[east.pk]))
        self.assertTrue(Region.objects.filter(pk=east.pk).exists())
        camp = Campus.objects.get(name="East Campus")
        self.client.post(reverse("organization:campus_delete", args=[camp.pk]))
        self.client.post(reverse("organization:region_delete", args=[east.pk]))
        self.assertFalse(Region.objects.filter(pk=east.pk).exists())

    def test_student_filters(self):
        c10 = Campus.objects.get(external_id="10")
        r = self.client.get(reverse("organization:student_list"), {"campus": c10.pk})
        self.assertContains(r, "Ali"); self.assertNotContains(r, "Sana")
        r = self.client.get(reverse("organization:student_list"), {"region": Region.objects.get(external_id="2").pk})
        self.assertContains(r, "Sana"); self.assertNotContains(r, "Ali")
        r = self.client.get(reverse("organization:student_list"), {"source": "manual"})
        self.assertNotContains(r, "Sana")
        r = self.client.get(reverse("organization:student_list"), {"q": "A-101"})
        self.assertContains(r, "Sana")

    def test_sync_settings_save_and_validation(self):
        r = self.client.post(reverse("organization:sync"), {
            "enabled": "on", "interval_minutes": 30, "deactivate_missing": "on",
            "sql_regions": "SELECT 1 AS external_id, 'x' AS name FROM dual",
            "sql_campuses": "SELECT 1 FROM dual", "sql_students": "SELECT 1 FROM dual"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(SyncSettings.load().enabled)
        r = self.client.post(reverse("organization:sync"), {
            "interval_minutes": 1, "sql_regions": "DROP TABLE x", "sql_campuses": "SELECT 1 FROM dual",
            "sql_students": "SELECT 1 FROM dual"})
        self.assertEqual(r.status_code, 200)

    def test_sync_now_and_test_buttons(self):
        with mock.patch("organization.views.start_background_sync") as start, \
                mock.patch("organization.views.oracle_configured", return_value=True):
            self.client.post(reverse("organization:sync_now"))
            start.assert_called_once_with("manual")
        with mock.patch("organization.views.start_background_sync") as start:
            self.client.post(reverse("organization:sync_now"))  # not configured
            start.assert_not_called()
        with mock.patch("organization.views.get_connector") as C:
            C.return_value.ping.side_effect = ConnectionError("down")
            r = self.client.post(reverse("organization:sync_test"), follow=True)
            self.assertContains(r, "Could not connect")

    def test_sync_page_shows_history_and_dashboard_card(self):
        self.assertContains(self.client.get(reverse("organization:sync")), "Success")
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "Oracle sync")

    def test_command_respects_disabled_flag(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("sync_oracle", stdout=out)
        self.assertIn("disabled", out.getvalue())


class DummyDataTests(TestCase):
    def test_generator_is_deterministic_and_consistent(self):
        from .mock import generate
        a, b = generate(60), generate(60)
        self.assertEqual(a, b)
        camp_ids = {c["external_id"] for c in a["campuses"]}
        reg_ids = {r["external_id"] for r in a["regions"]}
        self.assertTrue(all(c["region_id"] in reg_ids for c in a["campuses"]))
        self.assertTrue(all(s["campus_id"] in camp_ids for s in a["students"]))
        self.assertEqual(len({s["admission_no"] for s in a["students"]}), 60)
        self.assertEqual(len({s["external_id"] for s in a["students"]}), 60)

    def test_command_loads_then_round_two_changes(self):
        from django.core.management import call_command
        from io import StringIO
        call_command("load_dummy_data", students=100, stdout=StringIO())
        self.assertEqual(Region.objects.filter(source="oracle").count(), 3)
        self.assertEqual(Campus.objects.filter(source="oracle").count(), 14)
        self.assertEqual(StudentProfile.objects.filter(source="oracle").count(), 100)
        self.assertEqual(sorted(Region.objects.values_list("name", flat=True)), ["Central", "Northern", "Southern"])
        self.assertTrue(User.objects.filter(username__endswith="-26-0001").exists())
        out = StringIO()
        call_command("load_dummy_data", students=100, round=2, stdout=out)
        run = SyncRun.objects.first()
        self.assertEqual(run.status, "success", run.errors)
        self.assertEqual(run.stats["students_created"], 5)
        self.assertEqual(run.stats["students_deactivated"], 3)
        self.assertEqual(User.objects.filter(role="student", is_active=False).count(), 3)
        self.assertEqual(User.objects.filter(role="student").count(), 105)

    def test_reset_removes_only_oracle_data(self):
        from django.core.management import call_command
        from io import StringIO
        call_command("load_dummy_data", students=30, stdout=StringIO())
        manual = User.objects.create_user("manual1", password="x", role="student")
        StudentProfile.objects.create(user=manual, source="manual")
        call_command("load_dummy_data", reset=True, stdout=StringIO())
        self.assertEqual(StudentProfile.objects.filter(source="oracle").count(), 0)
        self.assertEqual(Region.objects.count(), 0)
        self.assertTrue(User.objects.filter(username="manual1").exists())

    def test_mock_mode_sync_page_and_buttons(self):
        from django.test import override_settings
        User.objects.create_superuser("admin", "a@x.com", "pw12345")
        self.client.login(username="admin", password="pw12345")
        with override_settings(ORACLE_MOCK=True, ORACLE_MOCK_STUDENTS=20):
            r = self.client.get(reverse("organization:sync"))
            self.assertContains(r, "Demo mode")
            self.assertContains(self.client.post(reverse("organization:sync_test"), follow=True), "Connection to Oracle works")
            run = run_sync("manual")
            self.assertEqual(run.status, "success")
            self.assertEqual(run.stats["students_created"], 20)
