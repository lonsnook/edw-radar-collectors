import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_all  # noqa: E402
from collectors import common, legistar, nc_con, socrata  # noqa: E402

CFG = {
    "include": ["multifamily", "apartment", "assisted living", "senior living"],
    "exclude": ["single-family", "hotel"],
    "min_units": 100,
}
TODAY = date(2026, 11, 9)


class FakeResp:
    def __init__(self, payload=None, text="", content=b""):
        self._payload, self.text, self.content = payload, text, content

    def json(self):
        return self._payload


class CommonTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(common.extract_units("New 372-unit apartment community"), 372)
        self.assertEqual(common.extract_units("120 apartments and 40 beds"), 120)
        self.assertIsNone(common.extract_units("clubhouse renovation"))

    def test_keywords_and_exclude(self):
        self.assertEqual(common.match_keywords("Multifamily project", CFG["include"], CFG["exclude"]), ["multifamily"])
        self.assertEqual(common.match_keywords("Hotel and apartment tower", CFG["include"], CFG["exclude"]), [])

    def test_id_is_stable(self):
        self.assertEqual(common.make_id("a", 1), common.make_id("a", 1))
        self.assertNotEqual(common.make_id("a", 1), common.make_id("a", 2))


class LegistarTests(unittest.TestCase):
    def test_filters_items(self):
        events = [
            {"EventId": 1, "EventBodyName": "Zoning Committee", "EventDate": "2026-11-12T00:00:00", "EventInSiteURL": "http://x/1"},
            {"EventId": 2, "EventBodyName": "Parks Committee", "EventDate": "2026-11-12T00:00:00", "EventInSiteURL": "http://x/2"},
        ]
        items = [
            {"EventItemId": 10, "EventItemTitle": "Rezoning petition for 250-unit multifamily community", "EventItemAgendaNote": ""},
            {"EventItemId": 11, "EventItemTitle": "Rezoning for a gas station", "EventItemAgendaNote": ""},
        ]

        def fake_get(url, params=None, **kw):
            return FakeResp(events if url.endswith("/events") else items)

        src = {"name": "Charlotte", "metro": "Charlotte", "client": "charlotte", "bodies": ["Zoning"]}
        with mock.patch.object(legistar, "http_get", fake_get):
            out = legistar.collect(src, CFG, TODAY)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["units"], 250)
        self.assertEqual(out[0]["date"], "2026-11-12")


class SocrataTests(unittest.TestCase):
    def test_cost_and_keywords(self):
        rows = [
            {"permit_": "A1", "issue_date": "2026-11-05T00:00:00", "work_description": "New 180-unit apartment building", "permit_type": "PERMIT - NEW CONSTRUCTION", "reported_cost": "42000000", "street_number": "100", "street_name": "MAIN"},
            {"permit_": "A2", "issue_date": "2026-11-05T00:00:00", "work_description": "New apartment building", "permit_type": "PERMIT - NEW CONSTRUCTION", "reported_cost": "50000"},
            {"permit_": "A3", "issue_date": "2026-11-05T00:00:00", "work_description": "New warehouse", "permit_type": "PERMIT - NEW CONSTRUCTION", "reported_cost": "9000000"},
        ]
        src = {"name": "Chicago", "metro": "Chicago", "domain": "d", "dataset": "x", "date_field": "issue_date", "id_field": "permit_",
               "type_field": "permit_type", "type_contains": "new construction", "text_fields": ["work_description", "permit_type"],
               "title_field": "work_description", "cost_field": "reported_cost", "min_cost": 3000000,
               "address_fields": ["street_number", "street_name"]}
        with mock.patch.object(socrata, "http_get", lambda *a, **k: FakeResp(rows)):
            out = socrata.collect(src, CFG, TODAY)
        self.assertEqual([o["title"][:12] for o in out], ["New 180-unit"])
        self.assertIn("$42,000,000", out[0]["detail"])


class NcConTests(unittest.TestCase):
    def test_links_and_lines(self):
        html = '<a href="/pdf/applicationLogMarch1-2026Reviews.pdf">a</a><a href="/pdf/applicationLogMarch1-2024Reviews.pdf">b</a><a href="/other.pdf">c</a>'
        links = nc_con.find_pdf_links(html, "https://info.ncdhhs.gov/dhsr/coneed/applicationlogs.html", 2026)
        self.assertEqual(links, ["https://info.ncdhhs.gov/pdf/applicationLogMarch1-2026Reviews.pdf"])
        lines = ["Wake  Oakwood Assisted Living  add 60 beds", "Durham  Imaging Center  new scanner"]

        def fake_get(url, **kw):
            return FakeResp(text=html, content=b"pdf")

        src = {"name": "CON", "metro": "North Carolina", "index_url": "https://info.ncdhhs.gov/dhsr/coneed/applicationlogs.html",
               "keywords": ["assisted living"]}
        with mock.patch.object(nc_con, "http_get", fake_get), mock.patch.object(nc_con, "pdf_lines", lambda c: lines):
            out = nc_con.collect(src, CFG, TODAY)
        self.assertEqual(len(out), 1)
        self.assertIn("Oakwood", out[0]["title"])


class RunTests(unittest.TestCase):
    def test_history_dedupe_and_isolation(self):
        item = common.make_item("S1", "Charlotte", "Planning agenda", "t", "d", "2026-11-10", "u", "id1")
        good = lambda src, cfg, today: [item]
        bad = lambda src, cfg, today: (_ for _ in ()).throw(RuntimeError("site down"))
        cfg = {"sources": [{"name": "S1", "type": "good"}, {"name": "S2", "type": "bad"}, {"name": "S3", "type": "good", "enabled": False}]}
        with tempfile.TemporaryDirectory() as d:
            log, added = run_all.run(cfg, d, TODAY, {"good": good, "bad": bad})
            self.assertEqual(len(added), 1)
            self.assertEqual(log["S1"]["status"], "ok")
            self.assertEqual(log["S2"]["status"], "error")
            self.assertEqual(log["S3"]["status"], "disabled")
            log2, added2 = run_all.run(cfg, d, date(2026, 11, 10), {"good": good, "bad": bad})
            self.assertEqual(len(added2), 0)
            saved = json.loads((Path(d) / "items.json").read_text())["items"]
            self.assertEqual(saved[0]["first_seen"], "2026-11-09")

    def test_prune_old(self):
        old = dict(common.make_item("S", "m", "k", "t", "d", "", "u", "old"), first_seen="2026-01-01")
        kept, added = run_all.merge([old], [], TODAY)
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()
