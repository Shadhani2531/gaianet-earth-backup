"""
Regression tests from the 12-month evaluation: GDACS impact rows for
multi-place disasters, and earthquake matching order.

GDACS impact rows are per-place reports. The original rule kept only the
latest row per country, which showed "1 death" for an Indonesian flood whose
rows report 120 deaths in one regency alone. Fixtures are real rows
(tests/fixtures/sendai_multi_place.py). No network access.

Run from backend/:   python -m unittest tests.test_disasters_evaluation -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import disasters as d                       # noqa: E402
from tests.fixtures import sendai_multi_place as fx         # noqa: E402
from tests.fixtures import rasuwa_2026 as rasuwa            # noqa: E402
from tests.fixtures import qinghai_2026 as qinghai          # noqa: E402


def _row(rows, label, country):
    return next(r for r in d.summarize_sendai(rows) if r["label"] == label and r["country"] == country)


class TestPlaceParsing(unittest.TestCase):
    def test_place_from_standard_description(self):
        self.assertEqual(d._sendai_place({"description": "939 [people] Fatalities in Bagmati Province, Nepal",
                                          "country": "Nepal"}), "Bagmati Province")

    def test_spaces_before_commas_normalised(self):
        self.assertEqual(d._sendai_place({"description": "16 [people] Fatalities in Gyirong Port , Gyirong County, "
                                                         "Shigatse, Tibet, China", "country": "China"}),
                         "Gyirong Port, Gyirong County, Shigatse, Tibet")

    def test_level_comma_name_format(self):
        self.assertEqual(d._sendai_place({"description": "Regency, Sibolga", "country": "Indonesia"}), "Sibolga")
        self.assertEqual(d._sendai_place({"description": "Country, Thailand", "country": "Thailand"}), "Thailand")

    def test_falls_back_to_region(self):
        self.assertEqual(d._sendai_place({"description": "", "region": "Aceh", "country": "Indonesia"}), "Aceh")


class TestMultiPlaceImpacts(unittest.TestCase):
    def test_indonesia_deaths_not_one_local_row(self):
        r = _row(fx.INDONESIA_DEATHS, "Deaths", "Indonesia")
        self.assertEqual(r["value"], 120)            # largest single report (Agam Regency)
        self.assertEqual(r["value_high"], 331)       # sum of the latest report of 12 places
        self.assertEqual(r["reports"], 12)
        self.assertEqual(r["places"][0]["place"], "Agam Regency, West Sumatra")

    def test_same_place_same_period_tie_keeps_highest(self):
        r = _row(fx.INDONESIA_DEATHS, "Deaths", "Indonesia")   # Agam: 120 and 74 for the same period
        self.assertIn("highest kept", r["note"])
        self.assertIn("double count", r["note"])

    def test_national_figure_not_added_to_provinces(self):
        r = _row(fx.THAILAND_AFFECTED, "Affected", "Thailand")
        self.assertEqual(r["value"], 697231)         # Songkhla Province alone
        self.assertEqual(r["value_high"], 702231)    # provinces 697,231 + 5,000; nationwide 456,000 not added

    def test_two_flood_waves_in_same_place_both_counted_in_high(self):
        r = _row(fx.ODISHA_EVACUATED, "Evacuated", "India")
        self.assertEqual(r["value"], 237000)         # August wave
        self.assertEqual(r["value_high"], 340070)    # + September wave 100,000 + two districts
        onsets = {p["onset"] for p in r["places"] if p["place"] == "Odisha"}
        self.assertEqual(onsets, {"2026-08-13", "2026-09-23"})

    def test_same_place_updates_are_never_summed(self):
        # Rasuwa: every row is Bagmati Province -> one place, latest figure only.
        rows = {(r["label"], r["country"]): r for r in d.summarize_sendai(rasuwa.SENDAI)}
        for r in rows.values():
            self.assertEqual(r["reports"], 1)
            self.assertIsNone(r["value_high"])
        self.assertEqual(rows[("Rescued", "Nepal")]["value"], 10451)


class TestEarthquakeMatchingOrder(unittest.TestCase):
    """Real records: an M5.7 and an M5.8 18 minutes apart within 8 km."""

    def test_time_first_matching_pairs_each_quake_with_its_own_record(self):
        g = [d.normalize_gdacs_feature(f) for f in qinghai.GDACS]
        u = [d.normalize_usgs_feature(f) for f in qinghai.USGS]
        pairs = {grp["primary"]["source_id"]: rel["event"]["source_id"]
                 for grp in d.link_events(g, u) for rel in grp["related"] if rel["relation"] == "same_event"}
        self.assertEqual(pairs, {"1554510": "us6000tga6", "1554511": "us6000tga9"})


if __name__ == "__main__":
    unittest.main()
