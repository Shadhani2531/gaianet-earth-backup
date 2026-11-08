"""
Ask Gaia's tools, after the Nov 2026 evaluation.

1. The current-conditions tool must report the same air quality as the
dashboard. It used to take AQI from the browser extension's alert helper
(OpenAQ only, 25 km, worst station), so in the Nov 2026 evaluation Gaia said
"no AQI station" for Mumbai, Chennai and Lahore while the dashboard showed a
value.

2. Same-name places: answer directly only for an overwhelmingly larger place
(New Delhi, Pune, Nairobi); ask for genuinely ambiguous names (Aurangabad).

No network access.
Run from backend/:   python -m unittest tests.test_gaia_tools -v
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import gaia_agent as g   # noqa: E402

CLIMATE = {"current": {"temperature_c": 30.2, "observation_time": "2026-11-05T19:15"},
           "current_anomaly": 1.1, "historical_trends": []}
ALERT = {"aqi_max": None, "data_source": {"air_quality": "no_station_in_radius"},
         "fire_count": 2, "fire_cluster_detected": False}


def _snapshot(env=None, env_error=None, alert=ALERT):
    env_patch = (patch.object(g.mock_data, "generate_environment_data", side_effect=env_error) if env_error
                 else patch.object(g.mock_data, "generate_environment_data", return_value=env))
    with patch.object(g.climate, "get_location_climate", return_value=CLIMATE), env_patch, \
            patch.object(g.alerts, "get_alert_summary", return_value=alert):
        return g._get_current_snapshot(19.07, 72.88)


class TestGaiaSnapshotAirQuality(unittest.TestCase):
    def test_aqi_comes_from_the_dashboard_chain_not_the_alert_helper(self):
        r = _snapshot({"air_quality_index": 142, "data_source": "live_waqi", "aqi_source": "WAQI station",
                       "aqi_station": {"name": "Bandra, Mumbai", "distance_km": 6.2},
                       "aqi_observed_at": "2026-11-05T18:00"})
        self.assertEqual(r["aqi"], 142)                       # alert helper had none
        self.assertEqual(r["aqi_data_source"], "live_waqi")
        self.assertEqual(r["aqi_station"], "Bandra, Mumbai")
        self.assertEqual(r["aqi_station_distance_km"], 6.2)
        self.assertFalse(r["aqi_is_model_estimate"])
        self.assertNotIn("aqi_unavailable_reason", r)

    def test_model_estimate_is_flagged(self):
        r = _snapshot({"air_quality_index": 96, "data_source": "model_openmeteo",
                       "aqi_source": "Open-Meteo CAMS model", "aqi_station": None})
        self.assertEqual(r["aqi"], 96)
        self.assertTrue(r["aqi_is_model_estimate"])
        self.assertIn("model estimate", g.SYSTEM_PROMPT)

    def test_unavailable_aqi_carries_the_reason(self):
        r = _snapshot({"air_quality_index": None, "data_source": "unavailable",
                       "aqi_reason": "WAQI: no station within 50 km; Open-Meteo: HTTP 429"})
        self.assertIsNone(r["aqi"])
        self.assertIn("429", r["aqi_unavailable_reason"])

    def test_one_failing_source_does_not_hide_the_others(self):
        r = _snapshot(env_error=RuntimeError("down"))
        self.assertEqual(r["temperature_c"], 30.2)
        self.assertNotIn("aqi", r)
        self.assertEqual(r["fire_count_nearby"], 2)


def _cand(label, pop, kind="town", lat=0.0, lon=0.0, exact=True, name=None):
    return {"label": label, "name": name or label.split(",")[0].strip(), "population": pop, "kind": kind,
            "lat": lat, "lon": lon, "exact": exact}


def _geocode(cands, place="X", said=None):
    """Run the geocoding tool; `said` simulates the user's words inside chat()."""
    token = g._USER_WORDS.set(said) if said is not None else None
    try:
        with patch("services.geocoding.search_places",
                   return_value={"status": "ok", "name": place.split(",")[0], "candidates": cands}) as sp:
            out = g._geocode_location(place)
        out["_searched"] = sp.called
        return out
    finally:
        if token is not None:
            g._USER_WORDS.reset(token)


class TestGaiaSameNamePlaces(unittest.TestCase):
    # Populations are rounded real-world figures, used only to exercise the rule.
    def test_major_city_with_village_namesakes_is_assumed_and_disclosed(self):
        r = _geocode([_cand("Pune, Maharashtra, India", 3_100_000, "city", 18.52, 73.86),
                      _cand("Pune, Oecusse, Timor-Leste", 0, "town"),
                      _cand("Pune, Pará, Brazil", 0, "town")])
        self.assertEqual((r["lat"], r["lon"]), (18.52, 73.86))
        self.assertTrue(r["assumed_most_prominent"])
        self.assertEqual(len(r["other_places_with_this_name"]), 2)
        self.assertIn("assumed", g.SYSTEM_PROMPT)

    def test_genuinely_ambiguous_name_is_still_a_question(self):
        r = _geocode([_cand("Aurangabad, Maharashtra, India", 1_200_000, "city"),
                      _cand("Aurangabad, Bihar, India", 102_000, "city")])       # ~12x, below 50x
        self.assertTrue(r["ambiguous"])
        self.assertNotIn("lat", r)

    def test_rival_city_without_population_blocks_the_shortcut(self):
        r = _geocode([_cand("Hyderabad, Telangana, India", 6_800_000, "city"),
                      _cand("Hyderabad, Sindh, Pakistan", None, "city")])
        self.assertTrue(r["ambiguous"])

    def test_small_places_are_never_assumed(self):
        r = _geocode([_cand("Springfield, Illinois", 90_000, "city"), _cand("Springfield, Somewhere", 0)])
        self.assertTrue(r["ambiguous"])                                     # top below 100,000

    def test_single_exact_match_unchanged(self):
        r = _geocode([_cand("Nagpur, Maharashtra, India", 2_400_000, "city", 21.15, 79.09)])
        self.assertEqual((r["lat"], r["lon"]), (21.15, 79.09))
        self.assertNotIn("assumed_most_prominent", r)


class TestUserWordsGuard(unittest.TestCase):
    """Evaluation (Nov 2026): the model sent "Nagpur" for "Nagpurr" and
    "Victoria, Australia" for "Victoria", bypassing the geocoding rules."""
    NAGPUR = [_cand("Nagpur, Maharashtra, India", 2_400_000, "city", 21.15, 79.09)]

    def test_spelling_correction_is_refused_before_searching(self):
        r = _geocode(self.NAGPUR, place="Nagpur", said="What's the AQI in Nagpurr?")
        self.assertTrue(r["name_not_from_user"])
        self.assertEqual(r["not_in_user_message"], ["Nagpur"])
        self.assertFalse(r["_searched"])

    def test_added_country_is_refused(self):
        r = _geocode([_cand("Victoria, Australia", 6_500_000, "state")], place="Victoria, Australia",
                     said="What's the fire risk in Victoria today?")
        self.assertEqual(r["not_in_user_message"], ["Australia"])

    def test_users_own_words_pass_with_case_accents_and_punctuation_ignored(self):
        r = _geocode(self.NAGPUR, place="Nagpur", said="how's nagpur's weather?")
        self.assertEqual((r["lat"], r["lon"]), (21.15, 79.09))
        r = _geocode([_cand("São Paulo, Brazil", 12_000_000, "city", -23.5, -46.6)], place="Sao Paulo",
                     said="AQI in São Paulo")
        self.assertEqual(r["lat"], -23.5)

    def test_whole_words_only(self):
        r = _geocode(self.NAGPUR, place="Nagpur", said="Is it raining in Nagpurr")
        self.assertTrue(r["name_not_from_user"])

    def test_no_check_outside_chat(self):
        r = _geocode(self.NAGPUR, place="Nagpur")
        self.assertIn("lat", r)

    def test_chat_records_only_the_users_messages_and_resets(self):
        seen = {}
        with patch.object(g, "_chat", side_effect=lambda *a, **k: seen.setdefault("w", g._USER_WORDS.get()) and {}):
            g.chat("the one in Bihar", history=[{"role": "user", "content": "AQI in Aurangabad?"},
                                                {"role": "assistant", "content": "Which Aurangabad? Maharashtra?"}])
        self.assertIn("Aurangabad", seen["w"])
        self.assertIn("Bihar", seen["w"])
        self.assertNotIn("Maharashtra", seen["w"])
        self.assertIsNone(g._USER_WORDS.get())


class TestAccentRivals(unittest.TestCase):
    """Hyderabad, Pakistan differs only by accents in the gazetteer, so it was
    not counted and Gaia assumed the Indian city (evaluation, Nov 2026)."""

    def test_accented_namesake_blocks_the_assumption_and_is_offered(self):
        r = _geocode([_cand("Hyderabad, Telangana, India", 6_800_000, "city"),
                      _cand("Hyderabad, Bhakkar, Pakistan", 0, "village"),
                      _cand("Hyderābād, Sindh, Pakistan", 1_700_000, "city", exact=False)], place="Hyderabad")
        self.assertTrue(r["ambiguous"])
        self.assertIn("Hyderābād, Sindh, Pakistan", r["options"])

    def test_single_exact_match_with_accented_rival_is_still_a_question(self):
        r = _geocode([_cand("Hyderabad, Telangana, India", 6_800_000, "city"),
                      _cand("Hyderābād, Sindh, Pakistan", 1_700_000, "city", exact=False)], place="Hyderabad")
        self.assertTrue(r["ambiguous"])

    def test_accent_only_match_is_never_answered_for(self):
        r = _geocode([_cand("Bhokāra, Maharashtra, India", 3_000, exact=False)], place="Bhokara")
        self.assertFalse(r["exact_match_found"])


class TestAqiWordingFromTools(unittest.TestCase):
    def test_categories_use_the_dashboard_bands(self):
        self.assertEqual([g._aqi_category(v) for v in (51, 95, 150, 177, 208, 223, 301)],
                         ["Moderate", "Moderate", "Unhealthy for sensitive groups", "Unhealthy",
                          "Very unhealthy", "Very unhealthy", "Hazardous"])
        self.assertIsNone(g._aqi_category(None))

    def test_snapshot_carries_the_category(self):
        r = _snapshot({"air_quality_index": 177, "data_source": "model_openmeteo"})
        self.assertEqual(r["aqi_category"], "Unhealthy")

    def test_forecast_carries_categories_and_who_guidelines(self):
        raw = {"days": [{"date": "2026-11-07", "aqi_max": 223, "pm25_max_ugm3": 190.9}], "status": "live"}
        with patch.object(g.forecast, "get_air_quality_forecast", return_value=raw):
            r = g._TOOL_DISPATCH["get_air_quality_forecast"]({"lat": 22.5, "lon": 88.4})
        self.assertEqual(r["days"][0]["aqi_category"], "Very unhealthy")
        self.assertEqual(r["who_2021_guideline_24h_ugm3"], {"pm2_5": 15, "pm10": 45})
        self.assertIn("aqi_category", g.SYSTEM_PROMPT)


class TestMethodsInPrompt(unittest.TestCase):
    """Evaluation D03: asked where temperatures come from, the model said
    "nearest weather stations" — the prompt never said. It now does."""

    def test_prompt_states_each_source(self):
        p = g.SYSTEM_PROMPT
        for phrase in ("exact coordinates (not a nearby weather station)", "ERA5", "WAQI station within 50 km",
                       "OpenAQ station within 25 km", "CAMS", "NASA FIRMS", "No live feature uses a trained"):
            self.assertIn(phrase, p)


class TestSnapshotSkipsOpenAQ(unittest.TestCase):
    def test_fire_lookup_does_not_query_openaq(self):
        from services import alerts
        with patch.object(alerts.nasa_firms, "get_wildfires_geojson", return_value={"features": []}), \
                patch.object(alerts.openaq_client, "get_stations_near") as near:
            out = alerts.get_alert_summary(19.07, 72.88, 50, include_air_quality=False)
        near.assert_not_called()
        self.assertEqual(out["data_source"]["air_quality"], "not_requested")


if __name__ == "__main__":
    unittest.main()
