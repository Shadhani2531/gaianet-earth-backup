"""
Ask Gaia — the conversational assistant described in the product
walkthrough. Deliberately NOT a free-floating chatbot: it answers using
function-calling ("tools") against this backend's OWN real endpoints
(climate, forecast, wildfire risk, alert summary), the same way a human
analyst would look the numbers up rather than guess them. This keeps
Gaia's answers grounded in the same honestly-labeled data — real,
fallback, or unavailable — as every chart and card elsewhere in the app,
instead of an LLM confidently hallucinating a plausible-sounding AQI.

Uses the OpenAI Chat Completions "tools" format via plain HTTP (no SDK
dependency, consistent with the rest of this codebase using `requests`
directly). GAIA_LLM_BASE_URL is configurable specifically so this can
point at OpenAI itself, or any OpenAI-compatible endpoint (OpenRouter,
Gemini's OpenAI-compatibility layer, a self-hosted vLLM server, etc.)
without a code change — see backend/.env.example.

If GAIA_LLM_API_KEY isn't set, this returns an honest "not configured"
response rather than a broken/fake one — the same fallback discipline as
every other service in this backend.
"""

import contextvars
import json
import re
import unicodedata
import logging
import os
from typing import Any, Dict, List, Optional

import requests

from services import climate, forecast, wildfire_risk, alerts, mock_data

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 10  # capped defensively — this endpoint has no
                            # persistent session store yet; the caller
                            # (frontend) resends recent turns each time


def _config() -> Dict[str, str]:
    return {
        "api_key": os.environ.get("GAIA_LLM_API_KEY", "").strip(),
        "model": os.environ.get("GAIA_LLM_MODEL", "openrouter/free").strip(),
        "base_url": os.environ.get("GAIA_LLM_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/"),
    }


def is_configured() -> bool:
    return bool(_config()["api_key"])


# --- Tools Gaia can call — thin wrappers around existing real services,
# no new upstream integrations introduced here ---

# --- The user's own words -------------------------------------------------
# The model may only look up a place name the user actually wrote. In the Nov
# 2026 evaluation it silently "fixed" Nagpurr -> Nagpur and Mumbaii -> Mumbai,
# and added countries the user never named (Victoria -> "Victoria, Australia",
# Valencia -> "Valencia, Spain"), which bypassed every geocoding rule. Prompt
# rules did not prevent it, so the geocoding tool now checks: every
# comma-separated part of place_name must appear, as whole words, in the
# user's messages of this conversation (case and accents ignored).
_USER_WORDS: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("gaia_user_words", default=None)


def _fold(text: Optional[str]) -> str:
    """Lower-case, accents removed, punctuation as spaces, single-spaced."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def _parts_not_from_user(place_name: str) -> List[str]:
    said = _USER_WORDS.get()
    if said is None:                     # called outside chat() (tests, scripts): no check
        return []
    hay = f" {_fold(said)} "
    return [part.strip() for part in (place_name or "").split(",")
            if _fold(part) and f" {_fold(part)} " not in hay]


# --- AQI wording comes from the tools, not the model ----------------------
# Evaluation (Nov 2026): the model called AQI 223 "Hazardous" and 177 "very
# unhealthy", and quoted WHO's PM10 guideline (45 ug/m3) as the PM2.5 one.
# The tools now return the category (same US EPA bands as the dashboard's
# Insight card, ui.js _aqiCategory) and the WHO 2021 24-hour guidelines.
WHO_2021_24H_UGM3 = {"pm2_5": 15, "pm10": 45}   # WHO global air quality guidelines, 2021


def _aqi_category(aqi: Optional[float]) -> Optional[str]:
    if aqi is None:
        return None
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for sensitive groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very unhealthy"
    return "Hazardous"


def _get_air_quality_forecast(lat: float, lon: float, days: int = 5) -> Dict[str, Any]:
    out = forecast.get_air_quality_forecast(lat, lon, days)
    if isinstance(out, dict):
        for d in out.get("days") or []:
            d["aqi_category"] = _aqi_category(d.get("aqi_max"))
        out["aqi_scale"] = "US EPA AQI"
        out["who_2021_guideline_24h_ugm3"] = dict(WHO_2021_24H_UGM3)
    return out


# A same-name place is answered for directly only when it is overwhelmingly
# the most prominent (Nov 2026 evaluation: Gaia asked "which New Delhi?"
# because a village in Illinois shares the name). Genuinely ambiguous names
# such as Aurangabad (Maharashtra ~10x Bihar) or Hyderabad still get a question.
DOMINANT_MIN_POPULATION = 100_000
DOMINANT_RATIO = 50
# A rival with no population figure (e.g. from OpenStreetMap) blocks the
# shortcut when it is this kind of place, so a big city is never overlooked
# just because its population is missing.
_MAJOR_KINDS = {"capital", "city", "municipality", "county", "state", "state_district", "province",
                "region", "district", "borough", "administrative"}


def _dominant_place(exact: List[Dict[str, Any]],
                    accent_rivals: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """The one exact match that dwarfs every other same-name place, or None.

    Rivals are the other exact matches PLUS places whose name matches once
    accents are removed (accent_rivals): those are never returned as an exact
    match themselves, but they can be the place the user means (Nov 2026:
    Hyderabad, Pakistan was not counted, so Gaia assumed the Indian city)."""
    rivals = [c for c in exact + (accent_rivals or [])]
    if not exact or len(rivals) < 2:
        return None
    top = max(exact, key=lambda c: c.get("population") or 0)
    p1 = top.get("population") or 0
    if p1 < DOMINANT_MIN_POPULATION:
        return None
    for c in rivals:
        if c is top:
            continue
        pop = c.get("population")
        if pop is None and (c.get("kind") or "").lower() in _MAJOR_KINDS:
            return None
        if (pop or 0) * DOMINANT_RATIO > p1:
            return None
    return top


def _geocode_location(place_name: str) -> Dict[str, Any]:
    """Real geocoding with disambiguation (services/geocoding.py).

    Coordinates are returned ONLY for a place whose name EXACTLY matches
    the requested name (case-insensitive; accents NOT folded, so "Bhokāra"
    is not "Bhokara"). Same rule the search bar now follows:
      - exactly one exact match   -> its coordinates
      - several exact matches, one overwhelmingly the largest (>=100,000
        people and >=50x every other)  -> its coordinates, flagged
        assumed_most_prominent, with the other places listed
      - several exact matches otherwise -> no coordinates; Gaia must ask which one
      (places whose name differs only by accents count as same-name rivals,
       but are never answered for themselves)
      - no exact match            -> no coordinates; Gaia must say so and may
                                     offer the near-spellings as questions,
                                     never answer for one of them
    Previously this fell back to candidates[0], so "Bhokara" could silently
    resolve to "Bhokra" — the same near-spelling bug fixed in search.
    (Matches within 15 km of each other are already merged as one place.)
    """
    from services import geocoding
    missing = _parts_not_from_user(place_name)
    if missing:
        return {
            "name_not_from_user": True,
            "requested_name": place_name,
            "not_in_user_message": missing,
            "instruction": ("The user did not write " + ", ".join(f"'{m}'" for m in missing) + ". Do not "
                            "correct the spelling or add a state or country yourself. Call "
                            "geocode_location again with the place name exactly as the user wrote it; "
                            "if that is ambiguous or not found, ask the user."),
        }
    try:
        res = geocoding.search_places(place_name)
        cands = res.get("candidates") or []
        if res.get("status") == "unavailable":
            return {"error": "Geocoding service unavailable right now."}
        exact = [c for c in cands if c.get("exact")]
        # Same name except for accents (e.g. "Hyderābād" for "Hyderabad"):
        # never answered for, but counted as a place the user may mean.
        qname = _fold(res.get("name") or place_name.split(",")[0])
        accent_rivals = [c for c in cands if not c.get("exact") and _fold(c.get("name")) == qname]

        if len(exact) == 1 and not accent_rivals:
            top = exact[0]
            return {"lat": top["lat"], "lon": top["lon"], "display_name": top["label"]}

        dominant = _dominant_place(exact, accent_rivals)
        if dominant is not None:
            return {
                "lat": dominant["lat"], "lon": dominant["lon"], "display_name": dominant["label"],
                "assumed_most_prominent": True,
                "other_places_with_this_name": [c["label"] for c in exact + accent_rivals
                                                if c is not dominant][:5],
                "instruction": ("Other, much smaller places share this name. Answer for this one, say "
                                "plainly which place you assumed (full name with state/country), and "
                                "mention that the user can name another place if they meant one."),
            }

        if exact:            # several places share the name (exactly or up to accents)
            return {
                "ambiguous": True,
                "options": [c["label"] for c in exact + accent_rivals][:6],
                "instruction": ("Several different places share this exact name. Do NOT pick one "
                                "and do NOT call any other tool for it yet. Ask the user which one "
                                "they mean, listing these options, and suggest replying like "
                                "'Name, State'."),
            }

        return {
            "exact_match_found": False,
            "requested_name": res.get("name") or place_name,
            "similar_names": [c["label"] for c in cands][:4],
            "instruction": ("No place with exactly this name was found. Do NOT answer for any of "
                            "the similar names and do NOT guess coordinates. Tell the user you "
                            "couldn't find that exact place; if similar names exist, ask whether "
                            "they meant one of them, or suggest selecting the spot on the map "
                            "(then ask about 'here')."),
        }
    except Exception as e:
        logger.warning(f"Gaia geocode failed for '{place_name}': {e}")
        return {"error": "Geocoding service unavailable right now."}


def _get_current_snapshot(lat: float, lon: float, radius_km: float = 50.0) -> Dict[str, Any]:
    """'What's happening right now' at a point, from the SAME services as the
    dashboard's Climate Insight card: temperature and anomaly from
    climate.get_location_climate(), air quality from
    mock_data.generate_environment_data() (WAQI station <=50 km -> OpenAQ
    station <=25 km -> Copernicus CAMS model, labelled as an estimate), and
    nearby fires from alerts.get_alert_summary().

    Air quality used to come from get_alert_summary() too. That helper is
    built for the browser extension's alerts: OpenAQ only, 25 km, worst
    station. So Gaia said "no AQI station" for Mumbai, Chennai and Lahore
    while the dashboard showed an AQI for the same place (evaluation,
    Nov 2026)."""
    result: Dict[str, Any] = {}
    try:
        climate_data = climate.get_location_climate(lat, lon)
        history = climate_data.get("historical_trends", [])
        latest = history[-1] if history else None
        result["temperature_c"] = (climate_data.get("current") or {}).get("temperature_c")
        result["temperature_observation_time"] = (climate_data.get("current") or {}).get("observation_time")
        result["temperature_anomaly_c"] = climate_data.get("current_anomaly")
    except Exception as e:
        logger.warning(f"Gaia snapshot: climate lookup failed: {e}")

    try:
        env = mock_data.generate_environment_data(lat, lon)
        station = env.get("aqi_station") or {}
        result["aqi"] = env.get("air_quality_index")
        result["aqi_category"] = _aqi_category(env.get("air_quality_index"))
        result["aqi_data_source"] = env.get("data_source")      # live_waqi | live_openaq | model_openmeteo | unavailable
        result["aqi_source"] = env.get("aqi_source")
        result["aqi_is_model_estimate"] = env.get("data_source") == "model_openmeteo"
        result["aqi_station"] = station.get("name")
        result["aqi_station_distance_km"] = station.get("distance_km")
        result["aqi_observed_at"] = env.get("aqi_observed_at")
        if env.get("air_quality_index") is None:
            result["aqi_unavailable_reason"] = env.get("aqi_reason")
    except Exception as e:
        logger.warning(f"Gaia snapshot: air quality lookup failed: {e}")

    try:
        summary = alerts.get_alert_summary(lat, lon, radius_km, include_air_quality=False)
        result["fire_count_nearby"] = summary.get("fire_count")
        result["fire_cluster_detected"] = summary.get("fire_cluster_detected")
    except Exception as e:
        logger.warning(f"Gaia snapshot: alert summary failed: {e}")

    return result


_TOOL_DISPATCH = {
    "geocode_location": lambda a: _geocode_location(a["place_name"]),
    "get_current_snapshot": lambda a: _get_current_snapshot(a["lat"], a["lon"], a.get("radius_km", 50.0)),
    "get_weather_forecast": lambda a: forecast.get_weather_forecast(a["lat"], a["lon"], a.get("days", 7)),
    "get_air_quality_forecast": lambda a: _get_air_quality_forecast(a["lat"], a["lon"], a.get("days", 5)),
    "get_wildfire_risk": lambda a: wildfire_risk.get_wildfire_risk(a["lat"], a["lon"]),
}

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "geocode_location",
            "description": "Convert a place name (city, region, landmark) into latitude/longitude. Call this first whenever the user names a place rather than giving coordinates or referring to 'here'/'this location'.",
            "parameters": {
                "type": "object",
                "properties": {"place_name": {"type": "string", "description": "e.g. 'Nagpur', 'Aurangabad, Bihar', 'Springfield, Illinois' — include state/country when the user gave it"}},
                "required": ["place_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_snapshot",
            "description": "Real current conditions at a point, the same values the dashboard shows: temperature, temperature anomaly, current AQI (nearest WAQI station within 50 km, else OpenAQ within 25 km, else the Copernicus CAMS model estimate — aqi_is_model_estimate says which), and nearby active fire count. Use this for 'right now' / 'currently' / 'is it safe outside today' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "radius_km": {"type": "number", "description": "Search radius for AQI stations and fires, default 50km"},
                },
                "required": ["lat", "lon"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "Real multi-day weather forecast (temperature, precipitation, wind) from Open-Meteo's NWP model. Use for questions about future days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "days": {"type": "integer", "description": "1-16, default 7"},
                },
                "required": ["lat", "lon"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_air_quality_forecast",
            "description": "Real multi-day AQI/PM2.5 forecast. Use for 'will the air quality be bad tomorrow/this weekend' type questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "days": {"type": "integer", "description": "1-5, default 5"},
                },
                "required": ["lat", "lon"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wildfire_risk",
            "description": "A transparent, formula-based fire danger score (0-100, Low/Moderate/High/Extreme) from real temperature, humidity, wind, and vegetation dryness (NDVI). This is NOT a trained ML model — say so if the user asks how it's calculated.",
            "parameters": {
                "type": "object",
                "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                "required": ["lat", "lon"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are Gaia, the conversational assistant built into GaiaNet Earth, a planetary environmental intelligence dashboard.

Rules you must follow:
1. Never guess or estimate a number (temperature, AQI, fire risk, forecast) yourself. Always call the relevant tool to get the real value before answering a question that needs one.
2. If the user names a place, call geocode_location first to get coordinates, unless coordinates were already given to you as the user's currently-selected map location. Pass place names to geocode_location exactly as the user wrote them — never correct a spelling or add a state or country the user did not give; if it returns "name_not_from_user", call it again with the user's own words. If geocode_location returns "assumed_most_prominent": true, answer for that place but say which place you assumed and that smaller places share the name. If it returns "ambiguous": true, several real places share that name — do NOT choose one; ask the user which they mean, listing the options it returned, and suggest replying like "Aurangabad, Bihar". If it returns "exact_match_found": false, say you couldn't find that exact place — never answer for a similar-sounding place and never invent coordinates; you may ask whether they meant one of the similar names, or suggest selecting the spot on the map. Always state the full place name (with state/country) you answered for.
3. If a tool returns an error or an "unavailable"/null value, say so honestly in plain language ("I couldn't get live air quality data for that spot right now") — never substitute a plausible-sounding made-up number. When aqi_is_model_estimate is true, say the AQI is a model estimate (Copernicus CAMS), not a station reading; when a station is given, you may name it and its distance. Describe an AQI only with the aqi_category the tool returns — never work out a category yourself — and quote guideline or threshold values only if a tool returned them (e.g. who_2021_guideline_24h_ugm3).
4. get_wildfire_risk is a documented rule-based formula, not a trained ML model — if asked how it works, say that plainly.
5. Keep answers short, plain-language, and directly useful for a real decision (e.g. "should I go outside", "should I reschedule an outdoor event"). Avoid dumping raw JSON at the user.
6. You are not a replacement for official emergency alerts or medical advice — for anything safety-critical, note that the person should also check official local sources.
7. If asked where the numbers come from, answer only from this list, and say you don't know anything it does not cover:
   - Current temperature: Open-Meteo's numerical weather model value at the exact coordinates (not a nearby weather station), with its time.
   - Temperature anomaly: the last 7 days compared with the same calendar days in 1991-2020, both from the ERA5 reanalysis (Open-Meteo archive).
   - Current AQI: the nearest WAQI station within 50 km, else an OpenAQ station within 25 km, else the Copernicus CAMS model estimate.
   - Weather forecasts: Open-Meteo numerical weather prediction. Air-quality forecasts: Copernicus CAMS forecasts via Open-Meteo.
   - Active fires: NASA FIRMS satellite detections. Vegetation (NDVI): NASA MODIS where available, otherwise a labelled biome estimate.
   - Fire danger: a documented rule-based formula of temperature, humidity, wind and NDVI. No live feature uses a trained machine-learning model.
"""


def chat(message: str, history: Optional[List[Dict[str, str]]] = None,
         context: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """One turn of conversation with Gaia (see _chat). Records the user's own
    words for this turn so the geocoding tool can refuse place names the
    user never wrote."""
    said = [message] + [m.get("content") or "" for m in (history or [])[-MAX_HISTORY_MESSAGES:]
                        if m.get("role") == "user"]
    token = _USER_WORDS.set("\n".join(said))
    try:
        return _chat(message, history, context)
    finally:
        _USER_WORDS.reset(token)


def _chat(message: str, history: Optional[List[Dict[str, str]]] = None,
          context: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    One turn of conversation with Gaia. `history` is a list of prior
    {role, content} messages the frontend resends each time (no
    server-side session store yet — this endpoint is stateless by
    design, matching the rest of this backend's no-persistent-session
    pattern outside the SQLite reports table).
    """
    config = _config()
    if not config["api_key"]:
        return {
            "reply": "Ask Gaia isn't configured yet — set GAIA_LLM_API_KEY in backend/.env to enable it.",
            "status": "not_configured",
            "location": None,
            "tool_calls_made": [],
        }

    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context and context.get("lat") is not None and context.get("lon") is not None:
        messages.append({
            "role": "system",
            "content": f"The user currently has this location selected on the dashboard's map: lat={context['lat']}, lon={context['lon']}. Use these coordinates for questions about 'here'/'this location' without a named place.",
        })
    if history:
        messages.extend(history[-MAX_HISTORY_MESSAGES:])
    messages.append({"role": "user", "content": message})

    last_location: Optional[Dict[str, Any]] = None
    tool_calls_made: List[Dict[str, Any]] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            resp = requests.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config["model"],
                    "messages": messages,
                    "tools": _TOOLS,
                    "tool_choice": "auto",
                },
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Gaia LLM call failed: {e}")
            return {
                "reply": "I couldn't reach the language model right now — try again shortly.",
                "status": "llm_unavailable",
                "location": last_location,
                "tool_calls_made": tool_calls_made,
            }

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return {
                "reply": (msg.get("content") or "").strip() or "I'm not sure how to answer that.",
                "status": "ok",
                "location": last_location,
                "tool_calls_made": tool_calls_made,
            }

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            handler = _TOOL_DISPATCH.get(fn_name)
            if handler is None:
                tool_result: Dict[str, Any] = {"error": f"Unknown tool '{fn_name}'"}
            else:
                try:
                    tool_result = handler(fn_args)
                except Exception as e:
                    logger.warning(f"Gaia tool '{fn_name}' failed: {e}")
                    tool_result = {"error": str(e)}

            tool_calls_made.append({"name": fn_name, "args": fn_args})

            if "lat" in fn_args and "lon" in fn_args:
                last_location = {"lat": fn_args["lat"], "lon": fn_args["lon"]}
            elif isinstance(tool_result, dict) and "lat" in tool_result and "lon" in tool_result:
                last_location = {
                    "lat": tool_result["lat"],
                    "lon": tool_result["lon"],
                    "name": tool_result.get("display_name"),
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(tool_result),
            })

    return {
        "reply": "I gathered some data but couldn't finish forming an answer — try rephrasing your question.",
        "status": "max_iterations_reached",
        "location": last_location,
        "tool_calls_made": tool_calls_made,
    }
