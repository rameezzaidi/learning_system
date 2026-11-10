from django.test import TestCase, override_settings


class CronTests(TestCase):
    @override_settings(CRON_SECRET="")
    def test_disabled_without_secret(self):
        self.assertEqual(self.client.get("/cron/daily/", HTTP_AUTHORIZATION="Bearer ").status_code, 403)

    @override_settings(CRON_SECRET="s3cret-value-for-test")
    def test_wrong_and_missing_token_rejected(self):
        self.assertEqual(self.client.get("/cron/daily/").status_code, 403)
        self.assertEqual(self.client.get("/cron/daily/", HTTP_AUTHORIZATION="Bearer nope").status_code, 403)

    @override_settings(CRON_SECRET="s3cret-value-for-test")
    def test_correct_token_runs_jobs(self):
        r = self.client.get("/cron/daily/", HTTP_AUTHORIZATION="Bearer s3cret-value-for-test")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"generate_fees", "scan_risk"})

    @override_settings(CRON_SECRET="s3cret-value-for-test")
    def test_post_not_allowed(self):
        self.assertEqual(self.client.post("/cron/daily/", HTTP_AUTHORIZATION="Bearer s3cret-value-for-test").status_code, 405)


class SetupTests(TestCase):
    @override_settings(CRON_SECRET="s3cret-value-for-test")
    def test_requires_post_and_secret(self):
        self.assertEqual(self.client.get("/cron/setup/").status_code, 405)
        self.assertEqual(self.client.post("/cron/setup/").status_code, 403)
        self.assertEqual(self.client.post("/cron/setup/", HTTP_AUTHORIZATION="Bearer x").status_code, 403)

    @override_settings(CRON_SECRET="")
    def test_disabled_without_secret(self):
        self.assertEqual(self.client.post("/cron/setup/", HTTP_AUTHORIZATION="Bearer ").status_code, 403)

    @override_settings(CRON_SECRET="s3cret-value-for-test")
    def test_migrate_runs(self):
        r = self.client.post("/cron/setup/", HTTP_AUTHORIZATION="Bearer s3cret-value-for-test")
        self.assertEqual((r.status_code, r.json()), (200, {"migrate": "ok"}))
