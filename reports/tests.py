from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organization.mock import MockOracle
from organization.services import run_sync

from . import engine


def make_rows(n_regions=2, n_campuses=2, per=13):
    rows = []
    for r in range(n_regions):
        for c in range(n_campuses):
            for s in range(per):
                rows.append(dict(name=f"S{r}{c}{s:02d}", username=f"u{r}{c}{s}", email="", phone="", admission=f"A{r}{c}{s}",
                                 active=True, status="Active", source="Manual", region=f"R{r}", campus=f"C{r}{c}", _no_campus=False))
    return rows


class EngineTests(TestCase):
    def test_pages_never_exceed_limit(self):
        pages, toc = engine.paginate(engine.build_lines(make_rows(), "region_campus"), 20)
        self.assertGreater(len(pages), 1)
        for p in pages:
            self.assertLessEqual(len(p), 20 + 2)

    def test_all_details_present_once(self):
        rows = make_rows()
        pages, _ = engine.paginate(engine.build_lines(rows, "region_campus"), 15)
        details = [ln for p in pages for ln in p if ln["t"] == "d"]
        self.assertEqual(len(details), len(rows))

    def test_grand_total_last(self):
        pages, _ = engine.paginate(engine.build_lines(make_rows(), "region_campus"), 25)
        self.assertEqual(pages[-1][-1]["t"], "grand")

    def test_toc_pages_valid(self):
        pages, toc = engine.paginate(engine.build_lines(make_rows(), "region_campus"), 15)
        self.assertTrue(toc)
        for t in toc:
            self.assertTrue(1 <= t["page"] <= len(pages))

    def test_page_links(self):
        self.assertEqual(engine.page_links(1, 3), [1, 2, 3])
        links = engine.page_links(10, 20)
        self.assertIn(None, links)
        self.assertIn(10, links)
        self.assertEqual(links[0], 1)
        self.assertEqual(links[-1], 20)


class ReportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        run_sync("command", MockOracle(60, 1))
        cls.admin = User.objects.create_user("boss", password="x", role="super_admin")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_table_view_paginates_and_sorts(self):
        r = self.client.get(reverse("reports:students"), {"per_page": 10, "sort": "campus", "dir": "desc", "page": 2})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["page_obj"].number, 2)
        self.assertEqual(len(r.context["page_obj"]), 10)

    def test_report_view_page_navigation(self):
        r = self.client.get(reverse("reports:students"), {"view": "report", "rpp": 15, "page": 2})
        self.assertEqual(r.context["current"], 2)
        self.assertGreater(r.context["total_pages"], 2)
        self.assertContains(r, "Page 2 of")

    def test_report_page_out_of_range_clamped(self):
        r = self.client.get(reverse("reports:students"), {"view": "report", "page": 999})
        self.assertEqual(r.context["current"], r.context["total_pages"])

    def test_print_renders_all_pages(self):
        r = self.client.get(reverse("reports:students"), {"view": "report", "print": 1})
        self.assertEqual(r.content.decode().count('class="paper"'), r.context["total_pages"])

    def test_csv(self):
        r = self.client.get(reverse("reports:students_csv"))
        self.assertEqual(r["Content-Type"].split(";")[0], "text/csv")
        self.assertGreater(len(r.content.decode("utf-8-sig").splitlines()), 60)

    def test_pdf(self):
        r = self.client.get(reverse("reports:students_pdf"))
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_admin_only(self):
        t = User.objects.create_user("t", password="x", role="teacher")
        self.client.force_login(t)
        self.assertEqual(self.client.get(reverse("reports:students")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reports:students_pdf")).status_code, 403)
