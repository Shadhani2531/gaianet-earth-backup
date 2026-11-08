"""
Grounding evaluation for Ask Gaia.

Runs every question in eval/gaia_questions.json through two systems that
use the SAME language model and endpoint (GAIA_LLM_* in backend/.env):

  gaia      Ask Gaia exactly as shipped: GaiaNet's system prompt + tools that
            call GaiaNet's own endpoints (services/gaia_agent.py).
  baseline  The same model as a plain chatbot: generic prompt, no tools.

and measures, per category:
  - value claims  numbers stated as environmental values (°C, %, mm, AQI,
                  µg/m³, scores ...); for gaia each is checked against the
                  numbers its tools actually returned; for the baseline,
                  which has no data access, every such value is unsupported
  - B  asks which place is meant (or names it fully) instead of guessing
  - C  says the place could not be found instead of answering
  - D  states its method/limits correctly (keyword check)
  - E  with a tool forced to fail, says the data is unavailable

Scores are automatic and approximate. Every reply is also written to a
review CSV with columns for manual correction; report the corrected figures.

Product code is NOT modified: the tools and the HTTP call are wrapped here
to record what each tool returned and to inject failures for category E.

Resumable: answers are appended to eval/results/gaia_eval_answers.jsonl and
skipped on the next run, so a run stopped by rate limits can be continued.

Run from backend/ (venv active):
    python eval/eval_gaia.py                    # both systems, all questions
    python eval/eval_gaia.py --systems gaia     # only one system
    python eval/eval_gaia.py --report           # rebuild summary from saved answers
Pin one model for a reproducible run, e.g. set GAIA_LLM_MODEL in backend/.env
to a specific tool-capable model rather than a router that changes models.
"""
import argparse
import csv
import json
import re
import sys
import time
import types
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except Exception:
    pass

from services import gaia_agent as g  # noqa: E402

QUESTIONS = BACKEND / "eval" / "gaia_questions.json"
RESULTS_DIR = BACKEND / "eval" / "results"
ANSWERS = RESULTS_DIR / "gaia_eval_answers.jsonl"
BASELINE_PROMPT = "You are a helpful assistant."

# ---------------------------------------------------------------------------
# value-claim extraction and grounding
# ---------------------------------------------------------------------------
# A minus sign only when it is not the dash of a range ("170-197", "24-26°C").
# Never starts inside a word or a longer number: the "2.5" of "PM2.5" is not a value.
_NUM = r"((?:(?<![\w.])-)?(?<![A-Za-z\d.])\d{1,4}(?:[.,]\d+)?)"
_NUM_RE = re.compile(_NUM)
_UNIT = (r"(\s*(?:°|º|˚)(?!\s*[NSEW]\b)\s*(?:[CF]\b)?|\s*degrees?(?:\s*(?:celsius|fahrenheit|c|f))?\b|\s*%|\s*percent\b|"
         r"\s*mm\b|\s*millimet(?:er|re)s?\b|\s*km/?h\b|\s*kph\b|\s*mph\b|\s*m/s\b|\s*(?:µ|μ|u)g/m(?:³|3)|\s*ppm\b)")
# (pattern, unit kind or None = read it from the matched unit text)
_PATTERNS = [
    (re.compile(_NUM + _UNIT, re.I), None),
    (re.compile(_NUM + r"\s*\(?\s*(?:on the\s*)?(?:US\s*)?AQI\b", re.I), "aqi"),
    (re.compile(_NUM + r"\s*(?:/|out of)\s*100\b", re.I), "score"),
]
# A keyword followed, on the same line and within `window` characters, by the
# value it names: "AQI in Lahore, Punjab, Pakistan is 173". Dates, clock times
# and counts on the way ("AQI for November 9 is 191") are skipped.
_KEYWORDS = [
    (re.compile(r"\b(?:AQI|air quality index)\b", re.I), "aqi", 50),
    (re.compile(r"\b(?:PM2\.5|PM10)\b", re.I), "conc", 50),
    (re.compile(r"\b(?:risk|danger|fire)\s*(?:score|index)\b", re.I), "score", 15),
]


def _unit_kind(text: str) -> str:
    t = (text or "").strip().lower()
    if t.endswith("f") or "fahrenheit" in t:
        return "F"
    if t.startswith(("°", "º", "˚", "degree")):
        return "C"
    if t in ("%", "percent"):
        return "%"
    if t.startswith("mm") or t.startswith("millimet"):
        return "mm"
    if t in ("km/h", "kmh", "kph", "mph", "m/s"):
        return "speed"
    if t == "ppm":
        return "ppm"
    return "conc"


_DATE_TAIL = re.compile(r"[-/.]\d{1,2}[-/.]\d{1,2}\b")
_DATE_HEAD = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]$|\b\d{1,2}[-/.]\d{1,2}[-/.]$")


_DATE_TOKEN = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b")


def _is_date_part(text: str, m: "re.Match", kind: Optional[str]) -> bool:
    """'2026-11-07' (any of its three numbers) or a bare year next to
    'PM2.5 ... tomorrow (2026' is a date, not a concentration or AQI."""
    if _DATE_TAIL.match(text, m.end(1)) or _DATE_HEAD.search(text[max(0, m.start(1) - 8):m.start(1)]):
        return True
    if any(d.start() <= m.start(1) < d.end()
           for d in _DATE_TOKEN.finditer(text, max(0, m.start(1) - 10), m.end(1) + 10)):
        return True
    if kind in ("aqi", "conc", "score"):
        try:
            v = float(m.group(1))
        except ValueError:
            return False
        return v.is_integer() and 1900 <= v <= 2100
    return False


_MONTH_BEFORE = re.compile(r"\b(?:january|february|march|april|may|june|july|august|september|october|"
                           r"november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\.?\s*$", re.I)
_ORDINAL_AFTER = re.compile(r"(?:st|nd|rd|th)\b", re.I)
# "AQI for the next 5 days", "AQI at 18:00", "a station 12 km away": not values.
# Nor is a ratio ("roughly 3-4 times the guideline", "3x").
_COUNT_AFTER = re.compile(r"\s*(?:-\s*\d+(?:[.,]\d+)?\s*)?(?:days?|hours?|hrs?|h\b|minutes?|mins?|km\b|kilomet|"
                          r"miles?|stations?|sensors?|monitors?|years?|yrs?|am\b|pm\b|a\.m\.|p\.m\.|"
                          r"times\b|fold\b|x\b|\u00d7)|:\d", re.I)


def _not_a_value(text: str, m: "re.Match", kind: Optional[str]) -> bool:
    """A date ("Nov 9", "9th", "2026-11-09"), a clock time or a count."""
    if _is_date_part(text, m, kind):
        return True
    if _MONTH_BEFORE.search(text[max(0, m.start(1) - 12):m.start(1)]) or _ORDINAL_AFTER.match(text, m.end(1)):
        return True
    if re.search(r"\d:$", text[max(0, m.start(1) - 3):m.start(1)]):     # the "00" of "18:00"
        return True
    return kind in ("aqi", "conc", "score") and bool(_COUNT_AFTER.match(text, m.end(1)))


# Markdown tables: a number in a column whose header names a unit is a value
# claim ("| Nov 9 | 191 | 186.7 |" under "| Date | Max AQI | PM2.5 (µg/m³) |").
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$")


def _column_kind(header: str) -> Optional[str]:
    h = _plain(header).lower()
    for pattern, kind in ((r"\baqi\b|air quality index", "aqi"),
                          (r"pm\s*2\.5|pm\s*10|[µμu]g/m", "conc"),
                          (r"(?:risk|danger|fire).*(?:score|index)|/\s*100", "score"),
                          (r"%|percent|humidity|probab|chance", "%"),
                          (r"°\s*f\b|fahrenheit", "F"),
                          (r"°|temp|celsius", "C"),
                          (r"\bmm\b|rain|precip", "mm"),
                          (r"km/?h|m/s|mph|wind", "speed"),
                          (r"\bppm\b|co2", "ppm")):
        if re.search(pattern, h):
            return kind
    return None


def _cells(line: str, base: int) -> List[tuple]:
    """(cell text, absolute start offset) for each cell of a table row."""
    s = line.rstrip("\r\n")
    pos = len(s) - len(s.lstrip())
    if s[pos:pos + 1] == "|":
        pos += 1
    cells, start = [], pos
    for j in range(pos, len(s)):
        if s[j] == "|":
            cells.append((s[start:j], base + start))
            start = j + 1
    if s[start:].strip():
        cells.append((s[start:], base + start))
    return cells


def value_claims(text: str) -> List[Dict[str, Any]]:
    """Numbers stated as environmental values, each with its unit kind."""
    text = text or ""
    seen, out = set(), []

    def add(m: "re.Match", kind: str) -> None:
        try:
            v = float(m.group(1).replace(",", "."))
        except ValueError:
            return
        seen.add(m.start(1))
        out.append({"v": v, "unit": kind})

    for pat, kind in _PATTERNS:
        for m in pat.finditer(text):
            if m.start(1) not in seen and not _not_a_value(text, m, kind):
                add(m, kind or _unit_kind(m.group(2)))

    for pat, kind, window in _KEYWORDS:
        for k in pat.finditer(text):
            line_end = text.find("\n", k.end())
            stop = len(text) if line_end < 0 else line_end
            for m in _NUM_RE.finditer(text, k.end(), stop):
                if m.start(1) - k.end() > window or m.start(1) in seen:
                    break                       # too far, or already another value's number
                if not _not_a_value(text, m, kind):
                    add(m, kind)
                    break

    lines = text.splitlines(keepends=True)
    offsets, o = [], 0
    for ln in lines:
        offsets.append(o)
        o += len(ln)
    kinds: Optional[List[Optional[str]]] = None
    for k, ln in enumerate(lines):
        if "|" not in ln:
            kinds = None
            continue
        if k > 0 and _TABLE_SEP.match(ln):
            kinds = [_column_kind(c) for c, _ in _cells(lines[k - 1], offsets[k - 1])]
            continue
        if kinds is None:
            continue
        for idx, (cell, start) in enumerate(_cells(ln, offsets[k])):
            kind = kinds[idx] if idx < len(kinds) else None
            if not kind:
                continue
            for m in _NUM_RE.finditer(text, start, start + len(cell)):   # first value in the cell
                if not _not_a_value(text, m, kind):
                    if m.start(1) not in seen:
                        add(m, kind)
                    break
    return out


def _flatten_numbers(obj: Any, out: List[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        try:
            out.append(float(obj))
        except ValueError:
            pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _flatten_numbers(v, out)


def is_supported(claim: Dict[str, Any], tool_numbers: List[float]) -> bool:
    """A claim is supported if some number the system was given matches it
    (rounding allowed); unit conversions apply only to the unit stated."""
    v, unit = claim["v"], claim["unit"]
    for t in tool_numbers:
        if unit == "F":
            if abs(v - (t * 9 / 5 + 32)) <= 1.0 or abs(v - t) <= 0.6:
                return True
        elif abs(v - t) <= max(0.6, 0.02 * abs(t)):
            return True
        elif unit == "%" and 0 <= t <= 1 and abs(v - t * 100) <= 1.0:
            return True
        elif unit == "speed" and (abs(v - t * 3.6) <= 1.0 or abs(v - t / 1.609) <= 1.0):
            return True
    return False


_RE_CLARIFY = re.compile(r"which (one|place|city|location|.{0,25} do you mean)|did you mean|several (places|locations|cities)|"
                         r"more than one|multiple (places|locations|cities)|could you (specify|clarify|tell me which)|"
                         r"please (specify|clarify|let me know which)", re.I)
_RE_NOTFOUND = re.compile(r"couldn'?t find|could not find|can'?t find|cannot find|wasn'?t able to find|unable to (find|locate)|"
                          r"no (exact )?(match|place|location|city)|not (able to )?(find|locate)|doesn'?t (seem to )?exist|"
                          r"not a real|fictional|did you mean", re.I)
_RE_UNAVAILABLE = re.compile(r"couldn'?t|could not|unavailable|not available|unable to|can'?t (get|retrieve|access|fetch)|"
                             r"isn'?t available|no (live |current )?data|didn'?t (return|get)|failed", re.I)


_TYPO = str.maketrans({"\u2019": "'", "\u2018": "'", "\u2011": "-", "\u2010": "-", "\u2013": "-", "\u00a0": " ",
                       "\u202f": " ", "\u2009": " ", "*": None,
                       **{chr(0x2080 + d): str(d) for d in range(10)}})


def _plain(text: str) -> str:
    """Curly apostrophes, non-breaking hyphens/spaces and subscript digits as
    plain ASCII, and markdown bold/italic stars removed, so the patterns match
    "I don\u2019t have access", "real\u2011time", "PM\u2082.\u2085" and "**AQI** is **173**" too."""
    return (text or "").translate(_TYPO)


def score_answer(item: Dict[str, Any], system: str, reply: str, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    reply = _plain(reply)
    claims = value_claims(reply)
    # Numbers the system was actually given: tool results and arguments, plus
    # map-context coordinates. The baseline has no tools, so only the latter.
    nums: List[float] = []
    for t in trace:
        _flatten_numbers(t["result"], nums)
        _flatten_numbers(t["args"], nums)
    _flatten_numbers(item.get("context") or {}, nums)
    unsupported = [v for v in claims if not is_supported(v, nums)]
    cat = item["category"]
    s: Dict[str, Any] = {"value_claims": claims, "unsupported_claims": unsupported,
                         "has_unsupported": bool(unsupported)}
    if cat == "B":
        ambiguous = any(isinstance(t["result"], dict) and t["result"].get("ambiguous") for t in trace)
        s["tool_reported_ambiguous"] = ambiguous
        s["asked_which"] = bool(_RE_CLARIFY.search(reply))
        s["pass"] = (s["asked_which"] and not claims) or (not ambiguous and bool(claims) and not unsupported
                                                        and system == "gaia")
    elif cat == "C":
        s["said_not_found"] = bool(_RE_NOTFOUND.search(reply))
        s["pass"] = s["said_not_found"] and not claims
    elif cat == "D":
        s["pass"] = bool(re.search(item.get("expect", "$^"), reply, re.I))
    elif cat == "E":
        s["said_unavailable"] = bool(_RE_UNAVAILABLE.search(reply))
        s["pass"] = s["said_unavailable"] and not unsupported
    else:  # A
        s["answered_with_values"] = bool(claims)
        s["pass"] = bool(claims) and not unsupported
    s["outcome"] = outcome(reply, s)
    return s


_RE_DECLINE = re.compile(r"(don'?t|do not) have (access|real[- ]time|live)|no (real[- ]time|live) (access|data)|"
                         r"(not able|unable) to (access|pull|provide|get|check)|can'?t (provide|access|check|tell you)|"
                         r"cannot (provide|access|check)", re.I)
_RE_MALFORMED = re.compile(r"<\|[a-z_]+\|>|tool_call_start", re.I)
OUTCOMES = ["tool-backed values", "unsupported values", "asked which place", "said not found",
            "said unavailable or declined", "empty or malformed", "no values (other)"]


def outcome(reply: str, s: Dict[str, Any]) -> str:
    """What the reply did, in one of OUTCOMES (automatic; check by hand)."""
    reply = _plain(reply)
    if not (reply or "").strip() or _RE_MALFORMED.search(reply):
        return "empty or malformed"
    if s["has_unsupported"]:
        return "unsupported values"
    if s["value_claims"]:
        return "tool-backed values"
    if _RE_CLARIFY.search(reply):
        return "asked which place"
    if _RE_NOTFOUND.search(reply):
        return "said not found"
    if _RE_UNAVAILABLE.search(reply) or _RE_DECLINE.search(reply):
        return "said unavailable or declined"
    return "no values (other)"


# ---------------------------------------------------------------------------
# running the two systems
# ---------------------------------------------------------------------------

class StopRun(BaseException):
    """Stops the whole run (daily limit, budget used up, repeated 429s).

    Derives from BaseException on purpose: gaia_agent.chat() catches every
    Exception from the HTTP call and turns it into an 'llm_unavailable'
    reply, which would record a failed answer and carry on burning quota.
    Nothing is recorded for the question in progress; the next run retries it.
    """


def _reset_text(value: Optional[str]) -> Optional[str]:
    """X-RateLimit-Reset as local time (ms or s since epoch, or seconds from now)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 1e12:
        ts = v / 1000
    elif v > 1e9:
        ts = v
    else:
        ts = time.time() + v
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class RateLimitedPost:
    """Wraps requests.post: paces calls, retries short 429/5xx bursts, stops the
    run on a daily limit or when the call budget is used up, and records the
    model actually served."""

    def __init__(self, pace_s: float, max_retries: int, budget: Optional[int] = None):
        self.pace_s, self.max_retries, self.budget = pace_s, max_retries, budget
        self.models: List[str] = []
        self.calls = 0

    def remaining(self) -> Optional[int]:
        return None if self.budget is None else self.budget - self.calls

    def __call__(self, *args, **kwargs):
        resp = None
        for attempt in range(self.max_retries + 1):
            if self.budget is not None and self.calls >= self.budget:
                raise StopRun(f"call budget of {self.budget} used up")
            time.sleep(self.pace_s)
            resp = requests.post(*args, **kwargs)
            self.calls += 1
            if resp.status_code == 429:
                body = (resp.text or "")[:400].lower()
                remaining = resp.headers.get("X-RateLimit-Remaining")
                reset = resp.headers.get("X-RateLimit-Reset")
                reset_txt = _reset_text(reset)
                far = False
                try:
                    rv = float(reset)
                    reset_ts = rv / 1000 if rv > 1e12 else (rv if rv > 1e9 else time.time() + rv)
                    far = reset_ts - time.time() > 600
                except (TypeError, ValueError):
                    pass
                if ("per-day" in body or "per day" in body or "daily" in body
                        or (remaining == "0" and far)):
                    raise StopRun("daily request limit reached"
                                  + (f"; it resets at {reset_txt}" if reset_txt else ""))
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    raise StopRun(f"provider still answering HTTP {resp.status_code} after "
                                  f"{self.max_retries} retries")
                wait = 10 * (2 ** attempt)
                print(f"      LLM HTTP {resp.status_code}; waiting {wait}s (retry {attempt + 1}/{self.max_retries})")
                time.sleep(wait)
                continue
            try:
                self.models.append(resp.json().get("model") or "?")
            except Exception:
                pass
            return resp
        return resp


def openrouter_quota() -> Optional[Dict[str, Any]]:
    """Free-model daily requests left on this OpenRouter key (None if unknown)."""
    cfg = g._config()
    if "openrouter.ai" not in cfg["base_url"]:
        return None
    try:
        r = requests.get(f"{cfg['base_url']}/key", headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        data = data.get("data", data)
        q = data.get("free_model_daily_requests")
        return q if isinstance(q, dict) else None
    except Exception:
        return None


# Typical LLM calls per answer (Gaia: plan, tool round(s), answer).
CALLS_PER_ANSWER = {"gaia": 3, "baseline": 1}


def run_gaia(item: Dict[str, Any], poster: RateLimitedPost) -> Dict[str, Any]:
    trace: List[Dict[str, Any]] = []
    original = dict(g._TOOL_DISPATCH)
    inject = item.get("inject")

    def wrap(name):
        def call(args):
            if inject and inject.get("tool") == name:
                result = inject["result"]
            else:
                try:
                    result = original[name](args)
                except Exception as e:      # gaia_agent reports it as an error; record it too
                    trace.append({"tool": name, "args": args, "result": {"error": str(e)}, "injected": False})
                    raise
            trace.append({"tool": name, "args": args, "result": result, "injected": bool(inject and inject.get("tool") == name)})
            return result
        return call

    poster.models.clear()
    g._TOOL_DISPATCH.update({n: wrap(n) for n in original})
    saved_requests = g.requests
    g.requests = types.SimpleNamespace(post=poster)
    try:
        out = g.chat(item["q"], history=None, context=item.get("context"))
    finally:
        g.requests = saved_requests
        g._TOOL_DISPATCH.clear()
        g._TOOL_DISPATCH.update(original)
    return {"reply": out.get("reply", ""), "status": out.get("status"), "trace": trace,
            "models": list(poster.models)}


def run_baseline(item: Dict[str, Any], poster: RateLimitedPost) -> Dict[str, Any]:
    cfg = g._config()
    poster.models.clear()
    messages = [{"role": "system", "content": BASELINE_PROMPT}, {"role": "user", "content": item["q"]}]
    if item.get("context"):
        messages[1]["content"] += f" (My location: lat {item['context']['lat']}, lon {item['context']['lon']}.)"
    try:
        resp = poster(f"{cfg['base_url']}/chat/completions",
                      headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
                      json={"model": cfg["model"], "messages": messages}, timeout=60)
        resp.raise_for_status()
        reply = (resp.json()["choices"][0]["message"].get("content") or "").strip()
        status = "ok"
    except Exception as e:
        reply, status = "", f"llm_unavailable: {e}"
    return {"reply": reply, "status": status, "trace": [], "models": list(poster.models)}


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def load_answers(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = path or ANSWERS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


_OK = ("ok", "max_iterations_reached")


def latest_ok(answers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Latest successful answer per (system, question)."""
    latest = {}
    for a in answers:
        if a["status"] in _OK:
            latest[(a["system"], a["id"])] = a
    return list(latest.values())


def report(all_answers: List[Dict[str, Any]]) -> str:
    answers = latest_ok(all_answers)
    pending = {(a["system"], a["id"]) for a in all_answers} - {(a["system"], a["id"]) for a in answers}
    by = defaultdict(list)
    for a in answers:
        by[(a["system"], a["category"])].append(a)
    names = {"A": "A  needs live numbers", "B": "B  ambiguous place", "C": "C  place not found",
             "D": "D  methods and limits", "E": "E  tool failure injected"}
    L = ["# Ask Gaia grounding evaluation (automatic scores — verify with the review CSV)", ""]
    models = sorted({m for a in answers for m in a.get("models", [])})
    L += [f"Models served: {', '.join(models) or 'n/a'}",
          f"Scored answers: {len(answers)} · still failing (re-run to retry): {len(pending)}", "",
          "## What each reply did", "",
          "| Category | System | n | " + " | ".join(OUTCOMES) + " |",
          "|---|---|---|" + "---|" * len(OUTCOMES)]
    for cat in "ABCDE":
        for system in ("gaia", "baseline"):
            rows = by.get((system, cat), [])
            if rows:
                counts = defaultdict(int)
                for r in rows:
                    counts[r["score"].get("outcome") or outcome(r["reply"], r["score"])] += 1
                L.append(f"| {names[cat]} | {system} | {len(rows)} | " + " | ".join(str(counts[o]) for o in OUTCOMES) + " |")
    L += ["", "## Expected behaviour per category (automatic)", "",
          "| Category | System | n | Pass | With unsupported values | Value claims (unsupported) |",
          "|---|---|---|---|---|---|"]
    for cat in "ABCDE":
        for system in ("gaia", "baseline"):
            rows = by.get((system, cat), [])
            if not rows:
                continue
            n = len(rows)
            passed = sum(1 for r in rows if r["score"]["pass"])
            unsup_q = sum(1 for r in rows if r["score"]["has_unsupported"])
            claims = sum(len(r["score"]["value_claims"]) for r in rows)
            unsup = sum(len(r["score"]["unsupported_claims"]) for r in rows)
            L.append(f"| {names[cat]} | {system} | {n} | {passed} ({100 * passed / n:.0f}%) | "
                     f"{unsup_q} ({100 * unsup_q / n:.0f}%) | {claims} ({unsup}) |")
    tools = [a for a in answers if a["system"] == "gaia" and a["category"] in "AB"]
    if tools:
        used = sum(1 for a in tools if a["trace"])
        L += ["", f"Gaia called at least one tool in {used} of {len(tools)} category A/B questions."]
    return "\n".join(L)


def write_review_csv(answers: List[Dict[str, Any]], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "category", "system", "question", "reply", "tools_called", "value_claims",
                    "unsupported_claims", "auto_outcome", "auto_pass", "manual_pass (fill Y/N)", "notes"])
        for a in answers:
            w.writerow([a["id"], a["category"], a["system"], a["question"], a["reply"],
                        "; ".join(t["tool"] + (" [INJECTED]" if t.get("injected") else "") for t in a["trace"]),
                        " ".join(f"{c['v']:g}{c['unit']}" for c in a["score"]["value_claims"]),
                        " ".join(f"{c['v']:g}{c['unit']}" for c in a["score"]["unsupported_claims"]),
                        a["score"].get("outcome", ""), "Y" if a["score"]["pass"] else "N", "", ""])


def _rescore(answers: List[Dict[str, Any]]) -> None:
    """Score saved answers with the current scoring code (in place)."""
    by_id = {q["id"]: q for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    for a in answers:
        if a.get("status") in _OK:
            item = by_id.get(a["id"], {"id": a["id"], "category": a["category"], "q": a.get("question", "")})
            a["score"] = score_answer(item, a["system"], a.get("reply", ""), a.get("trace") or [])


def retest_report(main_path: Path) -> str:
    """Before/after for questions re-asked with --retest."""
    before = {a["id"]: a for a in latest_ok(load_answers(main_path)) if a["system"] == "gaia"}
    after = {a["id"]: a for a in latest_ok(load_answers()) if a["system"] == "gaia"}
    _rescore(list(before.values()) + list(after.values()))
    L = ["# Ask Gaia re-test after fixes (main evaluation results unchanged)", "",
         "| Question | Before | After | Tools called after (geocode queries) |", "|---|---|---|---|"]
    for i in sorted(after):
        b, a = before.get(i), after[i]
        geo = [t["args"].get("place_name") for t in a["trace"] if t["tool"] == "geocode_location"]
        L.append(f"| {i}: {a['question']} | {b['score']['outcome'] if b else 'n/a'} | {a['score']['outcome']} | "
                 f"{', '.join(t['tool'] for t in a['trace']) or '-'} ({' → '.join(map(str, geo)) or '-'}) |")
    L += ["", "## Replies after the fixes", ""]
    for i in sorted(after):
        L += [f"### {i}: {after[i]['question']}", "", after[i]["reply"].strip(), ""]
    return "\n".join(L)


def main(argv=None) -> None:
    global ANSWERS
    ap = argparse.ArgumentParser(description="Ask Gaia grounding evaluation")
    ap.add_argument("--systems", default="gaia,baseline")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--limit", type=int, help="stop after this many new answers")
    ap.add_argument("--pace", type=float, default=4.0, help="seconds between LLM calls")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--budget", type=int, help="stop after this many LLM calls (default: OpenRouter's "
                    "remaining free requests for today, when available)")
    ap.add_argument("--report", action="store_true", help="only rebuild the summary from saved answers")
    ap.add_argument("--reset", choices=["gaia", "baseline", "all"],
                    help="set aside saved answers of this system (kept in a backup file) so they are asked again")
    ap.add_argument("--retest", help="comma-separated question ids to ask Gaia again after a fix; answers go "
                    "to gaia_eval_retest.jsonl and the main results are left untouched")
    args = ap.parse_args(argv)

    main_answers = ANSWERS
    if args.retest:
        ANSWERS = RESULTS_DIR / "gaia_eval_retest.jsonl"
        args.only, args.systems, args.reset = args.retest, "gaia", None

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.reset and ANSWERS.exists():
        drop = {"gaia", "baseline"} if args.reset == "all" else {args.reset}
        lines = ANSWERS.read_text(encoding="utf-8").splitlines(keepends=True)
        keep = [ln for ln in lines if ln.strip() and json.loads(ln).get("system") not in drop]
        backup = RESULTS_DIR / f"gaia_eval_answers_before_reset_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        backup.write_text("".join(lines), encoding="utf-8")
        ANSWERS.write_text("".join(keep), encoding="utf-8")
        print(f"Reset {args.reset}: {len(lines) - len(keep)} answers set aside (full copy in {backup.name}); "
              f"{len(keep)} kept.")
    if not args.report:
        if not g.is_configured():
            sys.exit("GAIA_LLM_API_KEY is not set in backend/.env — nothing to evaluate.")
        items = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
        if args.only:
            wanted = set(args.only.split(","))
            items = [i for i in items if i["id"] in wanted]
        done = {(a["system"], a["id"]) for a in latest_ok(load_answers())}
        systems = [x.strip() for x in args.systems.split(",") if x.strip()]
        todo = [(item, system) for item in items for system in systems      # paired: gaia then baseline
                if not (system == "baseline" and item["category"] == "E")   # no tools, nothing to inject
                and (system, item["id"]) not in done]
        cfg = g._config()
        print(f"Model: {cfg['model']} via {cfg['base_url']}")
        need = sum(CALLS_PER_ANSWER.get(sy, 1) for _, sy in todo)
        print(f"{len(todo)} answers to go (about {need} LLM calls).")
        budget = args.budget
        quota = openrouter_quota()
        if quota:
            print(f"OpenRouter free-model requests today: used {quota.get('used')}, "
                  f"remaining {quota.get('remaining')} of {quota.get('limit')}.")
            if budget is None and isinstance(quota.get("remaining"), int):
                budget = quota["remaining"]
        poster = RateLimitedPost(args.pace, args.max_retries, budget)
        new = 0
        stopped = None
        try:
            for item, system in todo:
                if args.limit is not None and new >= args.limit:
                    break
                left = poster.remaining()
                if left is not None and left < CALLS_PER_ANSWER.get(system, 1):
                    raise StopRun(f"only {left} calls left today")
                print(f"  {system:8} {item['id']}: {item['q']}")
                res = (run_gaia if system == "gaia" else run_baseline)(item, poster)
                rec = {"id": item["id"], "category": item["category"], "system": system, "question": item["q"],
                       "at": datetime.now(timezone.utc).isoformat(), **res,
                       "score": score_answer(item, system, res["reply"], res["trace"])}
                with open(ANSWERS, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, default=str) + "\n")
                new += 1
                if not res["status"].startswith("ok") and res["status"] != "max_iterations_reached":
                    print(f"      -> {res['status']} (will be retried on the next run)")
        except StopRun as e:
            stopped = str(e)
        if stopped:
            left_now = len(todo) - new
            print(f"\nStopped: {stopped}. {new} answers saved this run; {left_now} still to do.")
            print("Run the same command again later — saved answers are skipped.")
        print(f"{new} new answers; {poster.calls} LLM calls.")

    if args.retest:
        md = retest_report(main_answers)
        (RESULTS_DIR / "gaia_eval_retest_summary.md").write_text(md, encoding="utf-8")
        print("\n" + md.split("## Replies")[0])
        print("Saved: eval/results/gaia_eval_retest_summary.md (main results unchanged)")
        ANSWERS = main_answers
        return

    all_answers = load_answers()
    # Re-score every saved answer with the current scoring code, so a fix to
    # the scorer also applies to answers saved before it.
    _rescore(all_answers)
    md = report(all_answers)
    (RESULTS_DIR / "gaia_eval_summary.md").write_text(md, encoding="utf-8")
    write_review_csv(latest_ok(all_answers), RESULTS_DIR / "gaia_eval_review.csv")
    print("\n" + md)
    print("\nSaved: eval/results/gaia_eval_summary.md and gaia_eval_review.csv (fill in manual_pass to confirm scores)")


if __name__ == "__main__":
    main()
