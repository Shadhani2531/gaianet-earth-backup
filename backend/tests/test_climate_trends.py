"""
Regression tests: monthly climate trends and CO2 must never show invented
values, and the archive request must be cached. No network access.

Background: an earlier version replaced a failed or rate-limited Open-Meteo
archive request with a latitude/season formula plus random noise, and the
CO2 card fell back to a fixed 424.0 ppm that the UI badged LIVE. Both were
removed; these tests pin that down.

Run from backend/:   python -m unittest tests.test_climate_trends -v
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import climate, mock_data          # noqa: E402

NOW = datetime(2026, 11, 4, 12, 0)
POINT = (39.80, -122.95)


def _resp(payload, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload
    if status >= 400 and status != 429:
        m.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    else:
        m.raise_for_status = lambda: None
    return m


def _archive(days):
    """days: list of (date, temp_mean or None, precip or None)."""
    return {"daily": {"time": [d for d, _, _ in days],
                      "temperature_2m_mean": [t for _, t, _ in days],
                      "precipitation_sum": [p for _, _, p in days]}}


GOOD = _archive([
    ("2026-09-29", 20.0, 1.0), ("2026-09-30", 22.0, 2.5),
    ("2026-10-01", 18.0, 0.0), ("2026-10-02", 16.0, 4.0),
])


class TestNoSyntheticFallback(unittest.TestCase):
    def setUp(self):
        climate._trends_cache.clear()

    def test_synthetic_generator_is_gone(self):
        self.assertFalse(hasattr(climate, "_generate_fallback_data"))
        self.assertNotIn("random", climate.__dict__)

    def test_rate_limit_returns_no_months_and_a_reason(self):
        with patch.object(climate.requests, "get", return_value=_resp({}, status=429)):
            history, status = climate.get_live_climate_trends(*POINT, now=NOW)
        self.assertEqual(history, [])
        self.assertEqual(status["data_source"], "unavailable")
        self.assertIn("429", status["reason"])

    def test_network_error_returns_no_months_and_a_reason(self):
        with patch.object(climate.requests, "get", side_effect=requests.ConnectionError("down")):
            history, status = climate.get_live_climate_trends(*POINT, now=NOW)
        self.assertEqual(history, [])
        self.assertEqual(status["data_source"], "unavailable")
        self.assertIn("unreachable", status["reason"])

    def test_http_error_returns_no_months(self):
        with patch.object(climate.requests, "get", return_value=_resp({}, status=500)):
            history, status = climate.get_live_climate_trends(*POINT, now=NOW)
        self.assertEqual(history, [])
        self.assertEqual(status["data_source"], "unavailable")

    def test_empty_archive_is_unavailable_not_zero(self):
        with patch.object(climate.requests, "get", return_value=_resp({"daily": {}})):
            history, status = climate.get_live_climate_trends(*POINT, now=NOW)
        self.assertEqual(history, [])
        self.assertEqual(status["data_source"], "unavailable")


class TestMonthlySummary(unittest.TestCase):
    def test_monthly_means_and_totals(self):
        h = climate._summarize_monthly(GOOD["daily"])
        self.assertEqual([m["month"] for m in h], ["2026-09", "2026-10"])
        self.assertEqual(h[0]["avg_temp_c"], 21.0)
        self.assertEqual(h[0]["total_rainfall_mm"], 3.5)
        self.assertEqual(h[1]["avg_temp_c"], 17.0)
        self.assertEqual(h[1]["total_rainfall_mm"], 4.0)
        self.assertEqual(h[1]["data_through"], "2026-10-02")

    def test_measured_zero_rain_is_kept_as_zero(self):
        h = climate._summarize_monthly(_archive([("2026-10-01", 18.0, 0.0)])["daily"])
        self.assertEqual(h[0]["total_rainfall_mm"], 0.0)

    def test_missing_values_are_none_not_zero(self):
        h = climate._summarize_monthly(_archive([("2026-10-01", None, None),
                                                 ("2026-10-02", None, None)])["daily"])
        self.assertIsNone(h[0]["avg_temp_c"])
        self.assertIsNone(h[0]["total_rainfall_mm"])
        self.assertIsNone(h[0]["data_through"])


class TestTrendsCache(unittest.TestCase):
    def setUp(self):
        climate._trends_cache.clear()

    def test_second_call_is_served_from_cache(self):
        with patch.object(climate.requests, "get", return_value=_resp(GOOD)) as get:
            h1, s1 = climate.get_live_climate_trends(*POINT, now=NOW)
            h2, s2 = climate.get_live_climate_trends(*POINT, now=NOW)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(h1, h2)
        self.assertFalse(s1["cached"])
        self.assertTrue(s2["cached"])
        self.assertEqual(s2["data_source"], "real_openmeteo")

    def test_failures_are_not_cached(self):
        with patch.object(climate.requests, "get", return_value=_resp({}, status=429)):
            climate.get_live_climate_trends(*POINT, now=NOW)
        with patch.object(climate.requests, "get", return_value=_resp(GOOD)) as get:
            history, status = climate.get_live_climate_trends(*POINT, now=NOW)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(status["data_source"], "real_openmeteo")
        self.assertTrue(history)

    def test_new_day_refetches(self):
        with patch.object(climate.requests, "get", return_value=_resp(GOOD)) as get:
            climate.get_live_climate_trends(*POINT, now=NOW)
            climate.get_live_climate_trends(*POINT, now=datetime(2026, 11, 5, 12, 0))
        self.assertEqual(get.call_count, 2)

    def test_expired_entry_refetches(self):
        with patch.object(climate.requests, "get", return_value=_resp(GOOD)) as get:
            climate.get_live_climate_trends(*POINT, now=NOW)
            for key, (ts, h) in list(climate._trends_cache.items()):
                climate._trends_cache[key] = (ts - climate.TRENDS_CACHE_TTL_S - 1, h)
            climate.get_live_climate_trends(*POINT, now=NOW)
        self.assertEqual(get.call_count, 2)

    def test_cache_is_bounded(self):
        with patch.object(climate.requests, "get", return_value=_resp(GOOD)):
            for i in range(climate.TRENDS_MAX_CACHE_ENTRIES + 10):
                climate.get_live_climate_trends(10 + i * 0.1, 20.0, now=NOW)
        self.assertLessEqual(len(climate._trends_cache), climate.TRENDS_MAX_CACHE_ENTRIES)


class TestLocationClimate(unittest.TestCase):
    def setUp(self):
        climate._trends_cache.clear()

    def test_archive_failure_is_reported_not_filled(self):
        from services import current_conditions
        with patch.object(climate.requests, "get", side_effect=requests.ConnectionError("down")), \
             patch.object(current_conditions, "get_current_temperature",
                          return_value={"temperature_c": 12.3, "data_source": "real_openmeteo"}), \
             patch.object(current_conditions, "get_temperature_anomaly",
                          return_value={"anomaly_c": None, "status": "unavailable"}):
            res = climate.get_location_climate(*POINT)
        self.assertEqual(res["historical_trends"], [])
        self.assertEqual(res["data_source"], "unavailable")
        self.assertTrue(res["trends_reason"])
        self.assertEqual(res["current"]["temperature_c"], 12.3)


class TestCo2NeverInvented(unittest.TestCase):
    def setUp(self):
        self._saved = dict(mock_data._co2_cache)
        mock_data._co2_cache.update({"value": None, "fetched_at": None})

    def tearDown(self):
        mock_data._co2_cache.update(self._saved)

    def test_noaa_down_with_no_prior_value_is_none(self):
        with patch.object(mock_data.requests, "get", side_effect=requests.ConnectionError("down")):
            self.assertIsNone(mock_data.get_real_global_co2_ppm())
            fields = mock_data._co2_fields()
        self.assertEqual(fields, {"co2_ppm": None, "co2_data_source": "unavailable"})

    def test_noaa_down_keeps_last_real_value(self):
        mock_data._co2_cache.update({"value": 425.1, "fetched_at": datetime(2000, 1, 1)})
        with patch.object(mock_data.requests, "get", side_effect=requests.ConnectionError("down")):
            fields = mock_data._co2_fields()
        self.assertEqual(fields, {"co2_ppm": 425.1, "co2_data_source": "live_noaa_gml"})


if __name__ == "__main__":
    unittest.main()
