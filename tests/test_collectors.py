import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_all  # noqa: E402
from collectors import arcgis, common, legistar, nc_con, socrata  # noqa: E402

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


class ImprovedTests(unittest.TestCase):
    def test_acres(self):
        self.assertEqual(common.extract_acres("Total site area 4.5 acres"), 4.5)
        self.assertIsNone(common.extract_acres("no size"))

    def test_chicago_contacts_and_unit_change(self):
        rows = [{
            "permit_": "P1", "issue_date": "2026-11-05T00:00:00", "work_description": "New 11-story residential building",
            "permit_type": "PERMIT - NEW CONSTRUCTION", "reported_cost": "52000000", "street_number": "5853", "street_name": "BROADWAY",
            "residential_unit_change": "90",
            "contact_1_type": "ARCHITECT", "contact_1_name": "Studio Example LLC",
            "contact_2_type": "OWNER", "contact_2_name": "Broadway Holdings",
            "contact_3_type": "CONTRACTOR-GENERAL CONTRACTOR", "contact_3_name": "Build Co",
        }]
        src = {"name": "Chicago", "metro": "Chicago", "domain": "d", "dataset": "x", "date_field": "issue_date", "id_field": "permit_",
               "text_fields": ["work_description"], "title_field": "work_description", "cost_field": "reported_cost", "min_cost": 1,
               "address_fields": ["street_number", "street_name"], "contact_count": 15, "units_field": "residential_unit_change"}
        cfg = dict(CFG, min_units=50, include=["residential"])
        with mock.patch.object(socrata, "http_get", lambda *a, **k: FakeResp(rows)):
            out = socrata.collect(src, cfg, TODAY)
        self.assertEqual(out[0]["architect"], "Studio Example LLC")
        self.assertEqual(out[0]["owner"], "Broadway Holdings")
        self.assertEqual(out[0]["general_contractor"], "Build Co")
        self.assertEqual(out[0]["units"], 90)

    def test_dallas_text_dates(self):
        rows = [
            {"permit_number": "D1", "issued_date": "11/03/26", "work_description": "New multifamily apartments 200 units", "permit_type": "Building (BU) Multi Family  New Construction", "value": "40000000", "street_address": "1 MAIN ST", "contractor": "Big GC"},
            {"permit_number": "D2", "issued_date": "12/31/25", "work_description": "New multifamily apartments 200 units", "permit_type": "Building (BU) Multi Family  New Construction", "value": "40000000", "street_address": "2 MAIN ST"},
        ]
        src = {"name": "Dallas", "metro": "Dallas", "domain": "d", "dataset": "x", "date_field": "issued_date", "id_field": "permit_number",
               "server_date_filter": False, "date_format": "%m/%d/%y", "text_fields": ["work_description", "permit_type"],
               "title_field": "work_description", "cost_field": "value", "min_cost": 3000000, "address_fields": ["street_address"],
               "contractor_field": "contractor", "days_back": 21}
        with mock.patch.object(socrata, "http_get", lambda *a, **k: FakeResp(rows)):
            out = socrata.collect(src, CFG, TODAY)
        self.assertEqual([o["date"] for o in out], ["2026-11-03"])
        self.assertEqual(out[0]["general_contractor"], "Big GC")

    def test_nc_con_record_parsing(self):
        lines = [
            "I Burke E-012749-26 2/16/2026 $44,000,000 $50,000 No Not Yes 3/31/2026 943407 Grace Heights Health NF Relocate and construct a 120-bed replacement nursing facility",
            "A New Hanover E-012800-26 3/2/2026 $9,000,000 $20,000 No 111111 Castle Creek ACH",
            "Requested Hanover ACH beds from Castle Creek Memory Care, including 24 SCU beds",
            "I Wake E-012801-25 1/2/2025 $5,000,000 No 222222 Old Assisted Living project",
        ]
        html = '<a href="/dhsr/coneed/pdf/applicationLogs/2026/Log_Mar.pdf?ver=1.1">x</a>'
        src = {"name": "CON", "metro": "NC", "index_url": "https://info.ncdhhs.gov/dhsr/coneed/applicationlogs.html",
               "keywords": ["nursing", "memory care", "assisted living"]}

        def fake_get(url, **kw):
            return FakeResp(text=html, content=b"pdf")

        with mock.patch.object(nc_con, "http_get", fake_get), mock.patch.object(nc_con, "pdf_lines", lambda c: lines):
            out = nc_con.collect(src, CFG, TODAY)
        self.assertEqual(len(out), 2)  # the 2025 filing is older than a year
        burke = [o for o in out if o["county"] == "Burke"][0]
        self.assertEqual(burke["cost"], 44000000)
        self.assertEqual(burke["date"], "2026-02-16")
        self.assertEqual(burke["units"], 120)
        self.assertTrue(burke["title"].startswith("Burke County: Grace Heights"))

    def test_legistar_rezoning_review(self):
        events = [{"EventId": 1, "EventBodyName": "Zoning Committee", "EventDate": "2026-11-12T00:00:00", "EventInSiteURL": "http://x/1"}]
        items = [
            {"EventItemId": 10, "EventItemMatterId": 99, "EventItemTitle": "Rezoning Petition: 2026-050 by Acme Dev", "EventItemMatterFile": "15-1"},
            {"EventItemId": 11, "EventItemMatterId": 98, "EventItemTitle": "Rezoning Petition: 2026-051 by Gas Co", "EventItemMatterFile": "15-2"},
            {"EventItemId": 12, "EventItemMatterId": 99, "EventItemTitle": "Rezoning Petition: 2026-050 by Acme Dev", "EventItemMatterFile": "15-1"},
        ]
        atts = {99: [{"MatterAttachmentName": "2026-050-RevisedSitePlan", "MatterAttachmentHyperlink": "http://pdf/99"}],
                98: [{"MatterAttachmentName": "2026-051-RevisedSitePlan", "MatterAttachmentHyperlink": "http://pdf/98"}]}

        def fake_get(url, params=None, **kw):
            if url.endswith("/events"):
                return FakeResp(events)
            if url.endswith("/eventitems"):
                return FakeResp(items)
            if url.endswith("/attachments"):
                return FakeResp(atts[int(url.split("/")[-2])])
            return FakeResp(content=url.encode())

        plans = {b"http://pdf/99": "Site area 4.5 acres. Up to 280 multifamily dwelling units.", b"http://pdf/98": "Convenience store and fuel canopy."}
        src = {"name": "Charlotte", "metro": "Charlotte", "client": "charlottenc", "bodies": ["Zoning"], "also_review_titles": ["Rezoning Petition"]}
        with mock.patch.object(legistar, "http_get", fake_get), mock.patch.object(legistar, "pdf_text", lambda c: plans[c]):
            out = legistar.collect(src, CFG, TODAY)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["units"], 280)
        self.assertIn("4.5 acres", out[0]["detail"])
        self.assertEqual(out[0]["documents"][0]["name"], "2026-050-RevisedSitePlan")


class ArcgisTests(unittest.TestCase):
    def test_raleigh_rows(self):
        ms = 1793836800000  # 2026-11-05
        payload = {"features": [
            {"attributes": {"permitnum": "R1", "issueddate": ms, "proposedworkdescription": "New 4-story apartment building, 220 units", "estprojectcost": 41000000,
                            "housingunitstotal": 220, "streetnum": "100", "streetname": "OAK", "streettype": "ST", "parcelownername": "Oak Holdings LLC", "contractorcompanyname": "Triangle GC"}},
            {"attributes": {"permitnum": "R2", "issueddate": ms, "proposedworkdescription": "New warehouse", "estprojectcost": 9000000}},
        ]}
        src = {"name": "Raleigh", "metro": "Raleigh", "service_url": "https://x/FeatureServer/0", "date_field": "issueddate", "id_field": "permitnum",
               "text_fields": ["proposedworkdescription"], "title_field": "proposedworkdescription", "cost_field": "estprojectcost", "min_cost": 3000000,
               "units_field": "housingunitstotal", "address_fields": ["streetnum", "streetname", "streettype"], "contractor_field": "contractorcompanyname",
               "owner_field": "parcelownername", "days_back": 21}
        seen = {}

        def fake_get(url, params=None, **kw):
            seen.update(params)
            return FakeResp(payload)

        with mock.patch.object(arcgis, "http_get", fake_get):
            out = arcgis.collect(src, CFG, TODAY)
        self.assertIn("estprojectcost >= 3000000", seen["where"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["date"], "2026-11-05")
        self.assertEqual(out[0]["units"], 220)
        self.assertEqual(out[0]["owner"], "Oak Holdings LLC")
        self.assertEqual(out[0]["general_contractor"], "Triangle GC")


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
