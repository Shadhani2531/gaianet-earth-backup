"""
Twelve-month evaluation of GaiaNet Earth's hazard-reconciliation rules.

Downloads one year of GDACS and USGS records, runs GaiaNet's OWN functions
(services/disasters.py) on them, and measures:

  E1  Earthquake de-duplication (pass 1): precision / recall against the
      source event GDACS names in each quake's detail record (NEIC/USGS id),
      on a seeded random sample and on all Orange/Red quakes, a threshold
      grid, and how many quakes a dashboard without de-duplication would
      list twice.
  E2  "Active now": GaiaNet's status rule vs two naive rules ("started in the
      last 7 days" and "GDACS current flag only"), on a snapshot taken at
      run time. Each run appends its snapshot to results/hazard_snapshots.jsonl.
  E3  Flood/drought location (trap 1): how far GDACS's single point can be
      from parts of its own affected area; plus flood/drought <-> USGS
      landslide links over the year.
  E4  Impact rows (trap 2): naive summation of GDACS Sendai rows vs the
      old latest-row-per-country rule vs the current per-place range rule.
  E5  "Magnitude 0" severity on floods and droughts (trap 3).

Nothing is estimated: every number comes from the downloaded records.
Every download is cached under eval/data/hazards/, so the script can be
stopped and re-run (it resumes), and --offline re-analyses the cache only.

Run from backend/ (venv active):
    python eval/eval_hazards.py
    python eval/eval_hazards.py --offline          # re-analyse cached data
Options: --start YYYY-MM-DD --end YYYY-MM-DD (default: last 12 full months),
         --no-details, --no-geometry, --usgs-minmag 4.0, --eq-sample 400
"""
import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services import disasters as d  # noqa: E402

DATA_DIR = BACKEND / "eval" / "data" / "hazards"
RESULTS_DIR = BACKEND / "eval" / "results"
PAUSE_S = 0.4                      # politeness delay after each live request
HEADERS = {"User-Agent": "GaiaNet-Earth-research-evaluation/1.0"}
GDACS_ALL_TYPES = "EQ;TC;FL;VO;DR;WF"
DASHBOARD_EQ_MIN_MAG = 5.0         # /disasters default (main.py)
NAIVE_RECENT_DAYS = 7
SNAPSHOT_LOOKBACK_DAYS = 120

# Sensitivity grid for pass 1 (GaiaNet's values: 100 km, 1 h, 0.5)
GRID_KM = [25, 50, 100, 200]
GRID_H = [0.25, 0.5, 1, 2]
GRID_DMAG = [0.3, 0.5, 1.0]

_stats = {"live_requests": 0, "cache_hits": 0, "failed": []}


# ---------------------------------------------------------------------------
# download helpers (disk-cached, resumable)
# ---------------------------------------------------------------------------

def get_json(url: str, params: Dict[str, Any], cache_path: Path, offline: bool,
             retries: int = 4) -> Optional[Dict[str, Any]]:
    """GET with a disk cache. Returns None if unavailable (never invents data)."""
    if cache_path.exists():
        _stats["cache_hits"] += 1
        return json.loads(cache_path.read_text(encoding="utf-8"))
    if offline:
        return None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=45, headers=HEADERS)
            _stats["live_requests"] += 1
            if r.status_code == 204 or not r.content:
                data: Dict[str, Any] = {"features": [], "_status": 204}
            elif r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            elif 400 <= r.status_code < 500:
                data = {"_error": r.status_code}
            else:
                data = r.json()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
            time.sleep(PAUSE_S)
            return data
        except Exception as e:  # network error, 429, 5xx, bad JSON
            wait = 3 * (2 ** attempt)
            print(f"      retry {attempt + 1}/{retries} ({e}); waiting {wait}s")
            time.sleep(wait)
    _stats["failed"].append({"url": url, "params": params})
    return None


def month_chunks(start: date, end: date) -> List[Tuple[date, date]]:
    out, cur = [], start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        out.append((cur, min(end, nxt - timedelta(days=1))))
        cur = nxt
    return out


def fetch_gdacs(start: date, end: date, alerts: str, cache_tag: str, offline: bool) -> List[Dict[str, Any]]:
    """Raw GDACS features, month by month, latest episode per event."""
    latest: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    for ms, me in month_chunks(start, end):
        for page in range(1, 60):
            path = DATA_DIR / cache_tag / f"gdacs_{ms}_{me}_{alerts.replace(';', '')}_p{page}.json"
            data = get_json(d.GDACS_SEARCH_URL, {"eventlist": GDACS_ALL_TYPES, "fromdate": ms.isoformat(),
                                                 "todate": me.isoformat(), "alertlevel": alerts,
                                                 "pagenumber": page}, path, offline)
            if data is None:
                break
            feats = data.get("features") or []
            for f in feats:
                p = f.get("properties") or {}
                key = (p.get("eventtype"), p.get("eventid"))
                rank = (p.get("episodeid") or 0, p.get("todate") or "")
                if key not in latest or rank > latest[key][0]:
                    latest[key] = (rank, f)
            if len(feats) < d.GDACS_PAGE_SIZE:
                break
        print(f"    GDACS {ms}..{me}: {len(latest)} events so far")
    return [f for _, f in latest.values()]


def fetch_usgs(start: date, end: date, minmag: float, cache_tag: str, offline: bool) -> List[Dict[str, Any]]:
    feats: Dict[str, Dict[str, Any]] = {}
    for ms, me in month_chunks(start, end):
        base = {"format": "geojson", "starttime": ms.isoformat(),
                "endtime": (me + timedelta(days=1)).isoformat(), "orderby": "time", "limit": 20000}
        for kind, extra in (("earthquake", {"eventtype": "earthquake", "minmagnitude": minmag}),
                            ("landslide", {"eventtype": "landslide"})):
            path = DATA_DIR / cache_tag / f"usgs_{kind}_{ms}_{me}_m{minmag}.json"
            data = get_json(d.USGS_QUERY_URL, {**base, **extra}, path, offline)
            for f in (data or {}).get("features") or []:
                if f.get("id"):
                    feats[f["id"]] = f
        print(f"    USGS {ms}..{me}: {len(feats)} events so far")
    return list(feats.values())


# ---------------------------------------------------------------------------
# E1  earthquake de-duplication
# ---------------------------------------------------------------------------

_ID_TOKEN = re.compile(r"[a-z]{2}[0-9a-z]{6,12}", re.I)


def usgs_alias_map(raw_usgs: List[Dict[str, Any]]) -> Dict[str, str]:
    """Any id a USGS event is known by (its 'ids' list) -> its canonical id."""
    alias = {}
    for f in raw_usgs:
        fid = f["id"]
        alias[fid] = fid
        for i in ((f.get("properties") or {}).get("ids") or "").split(","):
            if i.strip():
                alias[i.strip()] = fid
    return alias


EQ_SAMPLE_DEFAULT = 400
EQ_SAMPLE_SEED = 2026


def eq_truth_from_details(raw_gdacs, alias: Dict[str, str], sample_n: int, offline: bool) -> Dict[str, Any]:
    """Reference matches from GDACS's own records. GDACS's search results leave
    'sourceid' empty, but each event's detail record names its source
    catalogue and event id (e.g. source 'NEIC', sourceid 'us7000s0pc').
    Reads a seeded random sample of all GDACS earthquakes (the same sample on
    every run, so --offline re-analysis reproduces it) plus every Orange/Red
    earthquake (shown by default on the dashboard)."""
    import random
    ids, alert = [], {}
    for f in raw_gdacs:
        p = f.get("properties") or {}
        if p.get("eventtype") == "EQ" and p.get("eventid") is not None:
            ids.append(p["eventid"])
            alert[p["eventid"]] = (p.get("alertlevel") or "").lower()
    order = sorted(set(ids))
    random.Random(EQ_SAMPLE_SEED).shuffle(order)
    sampled = set(order[:sample_n])
    significant = [i for i in sorted(set(ids)) if alert.get(i) in ("orange", "red") and i not in sampled]
    truth_sample, truth_sig, sources = {}, {}, Counter()
    unresolved, no_id, sample_read = [], 0, 0
    chosen = order[:sample_n] + significant
    for n, i in enumerate(chosen, 1):
        raw = get_json(d.GDACS_EVENT_URL, {"eventtype": "EQ", "eventid": i},
                       DATA_DIR / "details" / f"EQ_{i}.json", offline)
        if n % 50 == 0:
            print(f"    earthquake details {n}/{len(chosen)}")
        if not raw or raw.get("_error") or raw.get("_status") == 204:
            continue
        p = raw.get("properties") or {}
        src, sid = p.get("source"), (p.get("sourceid") or "").strip()
        sources[src or "none"] += 1
        sample_read += i in sampled
        if not sid:
            no_id += 1
            continue
        target = alias.get(sid)
        if not target:
            unresolved.append(sid)
            continue
        gid = f"gdacs:EQ:{i}"
        if i in sampled:
            truth_sample[gid] = target
        if alert.get(i) in ("orange", "red"):
            truth_sig[gid] = target
    return {"sample": truth_sample, "significant": truth_sig, "sources": dict(sources),
            "details_read": sum(sources.values()), "random_sample_requested": sample_n,
            "random_sample_read": sample_read, "no_source_id": no_id,
            "source_id_not_in_usgs_set": len(unresolved), "unresolved_sample": unresolved[:10]}


def _components(gdacs: List[Dict], usgs: List[Dict], max_km: float, max_h: float) -> List[Tuple[List, List]]:
    """Connected components of the loosest candidate graph. Running
    link_events per component is exactly equivalent to one global run
    (pass-1 matching never crosses components) and far faster."""
    us = sorted(usgs, key=lambda u: d._parse_dt(u["start"]))
    times = [d._parse_dt(u["start"]).timestamp() for u in us]
    import bisect
    parent: Dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for g in gdacs:
        find(g["id"])
        t = d._parse_dt(g["start"]).timestamp()
        lo, hi = bisect.bisect_left(times, t - max_h * 3600), bisect.bisect_right(times, t + max_h * 3600)
        for u in us[lo:hi]:
            if d.haversine_km(g["lat"], g["lon"], u["lat"], u["lon"]) <= max_km:
                parent[find(u["id"])] = find(g["id"])
    comps: Dict[str, Tuple[List, List]] = defaultdict(lambda: ([], []))
    for g in gdacs:
        comps[find(g["id"])][0].append(g)
    for u in us:
        if u["id"] in parent:
            comps[find(u["id"])][1].append(u)
    return list(comps.values())


def run_pass1(comps, km: float, h: float, dmag: float) -> Dict[str, str]:
    saved = (d.EQ_DUPLICATE_KM, d.EQ_DUPLICATE_H, d.EQ_DUPLICATE_DMAG)
    d.EQ_DUPLICATE_KM, d.EQ_DUPLICATE_H, d.EQ_DUPLICATE_DMAG = km, h, dmag
    try:
        pred = {}
        for gs, us in comps:
            if not us:
                continue
            for grp in d.link_events(gs, us):
                for rel in grp["related"]:
                    if rel["relation"] == "same_event":
                        pred[grp["primary"]["id"]] = rel["event"]["source_id"]
        return pred
    finally:
        d.EQ_DUPLICATE_KM, d.EQ_DUPLICATE_H, d.EQ_DUPLICATE_DMAG = saved


def score(pred: Dict[str, str], truth: Dict[str, str]) -> Dict[str, Any]:
    tp = sum(1 for g, u in truth.items() if pred.get(g) == u)
    predicted = sum(1 for g in truth if g in pred)
    return {"evaluable": len(truth), "predicted": predicted, "correct": tp,
            "precision": round(tp / predicted, 4) if predicted else None,
            "recall": round(tp / len(truth), 4) if truth else None}


def e1_earthquakes(raw_gdacs, raw_usgs, sample_n: int, offline: bool) -> Dict[str, Any]:
    alias = usgs_alias_map(raw_usgs)
    gdacs_eq = []
    for f in raw_gdacs:
        if (f.get("properties") or {}).get("eventtype") != "EQ":
            continue
        ev = d.normalize_gdacs_feature(f)
        if ev and ev.get("start"):
            gdacs_eq.append(ev)
    usgs_eq = [ev for ev in (d.normalize_usgs_feature(f) for f in raw_usgs)
               if ev and ev["hazard"] == "earthquake" and ev.get("start")]
    comps = _components(gdacs_eq, usgs_eq, max(GRID_KM), max(GRID_H))
    ref = eq_truth_from_details(raw_gdacs, alias, sample_n, offline)

    pred = run_pass1(comps, d.EQ_DUPLICATE_KM, d.EQ_DUPLICATE_H, d.EQ_DUPLICATE_DMAG)
    grid = []
    for km in GRID_KM:
        for h in GRID_H:
            for dm in GRID_DMAG:
                pg = pred if (km, h, dm) == (d.EQ_DUPLICATE_KM, d.EQ_DUPLICATE_H, d.EQ_DUPLICATE_DMAG) \
                    else run_pass1(comps, km, h, dm)
                grid.append({"km": km, "h": h, "dmag": dm, "matched_total": len(pg),
                             "sample": score(pg, ref["sample"]), "significant": score(pg, ref["significant"])})
    errors = [{"gdacs": g, "reference": u, "predicted": pred.get(g)}
              for truth in (ref["sample"], ref["significant"]) for g, u in truth.items() if pred.get(g) != u]
    return {
        "gdacs_earthquakes": len(gdacs_eq),
        "usgs_earthquakes": len(usgs_eq),
        "reference": {k: v for k, v in ref.items() if k not in ("sample", "significant")},
        "gaianet_thresholds": {"km": d.EQ_DUPLICATE_KM, "h": d.EQ_DUPLICATE_H, "dmag": d.EQ_DUPLICATE_DMAG},
        "gaianet_random_sample": score(pred, ref["sample"]),
        "gaianet_orange_red": score(pred, ref["significant"]),
        "matched_total": len(pred),
        "listed_twice_without_dedup": len(pred),
        "listed_twice_without_dedup_note": ("GDACS earthquakes that also appear in the USGS feed and would be "
                                            "shown as two events if pass 1 were removed (GaiaNet's own matches)."),
        "errors_sample": errors[:20],
        "sensitivity": grid,
    }


# ---------------------------------------------------------------------------
# E2  active-now snapshot
# ---------------------------------------------------------------------------

def e2_snapshot(raw_gdacs_recent, raw_usgs_recent, now: datetime) -> Dict[str, Any]:
    gdacs = [ev for ev in (d.normalize_gdacs_feature(f) for f in raw_gdacs_recent) if ev and ev.get("start")]
    usgs = [ev for ev in (d.normalize_usgs_feature(f) for f in raw_usgs_recent)
            if ev and ev.get("start") and (ev["hazard"] == "landslide"
                                          or (ev.get("magnitude") or 0) >= DASHBOARD_EQ_MIN_MAG)]
    rows = []
    for ev in gdacs + usgs:
        status, basis = d.group_status({"primary": ev}, now)
        start = d._parse_dt(ev["start"])
        age_d = (now - start).total_seconds() / 86400
        naive_recent = 0 <= age_d <= NAIVE_RECENT_DAYS
        naive_flag = bool(ev.get("is_current")) if ev["source"] == "GDACS" else False
        if ev["source"] != "GDACS":
            why = "usgs_instantaneous"
        elif not ev.get("is_current"):
            why = "gdacs_not_current"
        elif not ev.get("end") or ev["end"] <= ev["start"]:
            why = "gdacs_instantaneous"
        elif status == "ended":
            why = "gdacs_stale_flag"
        else:
            why = "gdacs_current"
        rows.append({"id": ev["id"], "hazard": ev["hazard"], "alert": ev.get("alert"), "age_days": round(age_d, 1),
                     "gaianet_active": status == "active", "naive_recent": naive_recent,
                     "naive_flag": naive_flag, "why": why})
    act = [r for r in rows if r["gaianet_active"]]
    fp_recent = [r for r in rows if r["naive_recent"] and not r["gaianet_active"]]
    fn_recent = [r for r in rows if r["gaianet_active"] and not r["naive_recent"]]
    fp_flag = [r for r in rows if r["naive_flag"] and not r["gaianet_active"]]
    sig = {"orange", "red"}
    return {
        "taken_at": now.isoformat(),
        "events_considered": len(rows),
        "gaianet_active": len(act),
        "gaianet_active_significant": sum(1 for r in act if r["alert"] in sig),
        "naive_recent_active": sum(1 for r in rows if r["naive_recent"]),
        "naive_recent_but_ended": len(fp_recent),
        "naive_recent_but_ended_by_reason": dict(Counter(r["why"] for r in fp_recent)),
        "naive_recent_but_ended_by_hazard": dict(Counter(r["hazard"] for r in fp_recent)),
        "ongoing_missed_by_naive_recent": len(fn_recent),
        "ongoing_missed_ages_days": sorted(r["age_days"] for r in fn_recent),
        "ongoing_missed_by_hazard": dict(Counter(r["hazard"] for r in fn_recent)),
        "naive_flag_active": sum(1 for r in rows if r["naive_flag"]),
        "naive_flag_but_not_active": len(fp_flag),
        "naive_flag_but_not_active_by_reason": dict(Counter(r["why"] for r in fp_flag)),
        "rules": {"naive_recent": f"started within the last {NAIVE_RECENT_DAYS} days",
                  "naive_flag": "GDACS iscurrent flag alone",
                  "gaianet": "GDACS iscurrent AND has a duration AND latest episode within the hazard's staleness window; USGS never active"},
    }


# ---------------------------------------------------------------------------
# E3  flood / drought point vs affected area, and landslide links
# ---------------------------------------------------------------------------

def _vertices(geometry):
    for ring in d._rings(geometry):
        for lon, lat in ring:
            yield lat, lon


def _quantiles(xs: List[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0}
    xs = sorted(xs)
    q = statistics.quantiles(xs, n=4) if len(xs) >= 2 else [xs[0]] * 3
    return {"n": len(xs), "median": round(statistics.median(xs), 1), "p25": round(q[0], 1),
            "p75": round(q[2], 1), "max": round(xs[-1], 1)}


def geometry_for(ev, offline: bool) -> Optional[Dict[str, Any]]:
    path = DATA_DIR / "geometry" / f"{ev['gdacs_type']}_{ev['source_id']}_{ev.get('episode_id')}.json"
    params = {"eventtype": ev["gdacs_type"], "eventid": ev["source_id"]}
    if ev.get("episode_id") is not None:
        params["episodeid"] = ev["episode_id"]
    raw = get_json(d.GDACS_GEOMETRY_URL, params, path, offline)
    if not raw or raw.get("_error") or raw.get("_status") == 204:
        return None
    sel = d.select_affected_polygon(raw)
    return sel if sel.get("geometry") else None


def e3_area_events(raw_gdacs, raw_usgs, offline: bool, with_geometry: bool) -> Dict[str, Any]:
    area = [ev for ev in (d.normalize_gdacs_feature(f) for f in raw_gdacs)
            if ev and ev["gdacs_type"] in ("FL", "DR") and ev.get("alert") in ("orange", "red")]
    out: Dict[str, Any] = {"orange_red_flood_drought_events": len(area)}
    if with_geometry:
        inside, parts, dist_out, spread = 0, [], [], []
        with_geom = 0
        for i, ev in enumerate(area, 1):
            g = geometry_for(ev, offline)
            if i % 25 == 0:
                print(f"    geometry {i}/{len(area)}")
            if not g:
                continue
            with_geom += 1
            geom = g["geometry"]
            n_parts = len(d._polygons(geom)) or 1
            parts.append(n_parts)
            if d.point_in_geometry(ev["lat"], ev["lon"], geom):
                inside += 1
            else:
                dist_out.append(d.distance_to_geometry_km(ev["lat"], ev["lon"], geom) or 0.0)
            spread.append(max((d.haversine_km(ev["lat"], ev["lon"], la, lo) for la, lo in _vertices(geom)),
                              default=0.0))
        out.update({
            "with_polygon": with_geom,
            "point_inside_polygon": inside,
            "point_outside_polygon": with_geom - inside,
            "outside_distance_km": _quantiles(dist_out),
            "multi_part_polygons": sum(1 for p in parts if p > 1),
            "farthest_affected_vertex_from_point_km": _quantiles(spread),
            "farthest_over_100km": sum(1 for s in spread if s > 100),
        })

    # Flood/drought <-> USGS landslide links over the year (all alert levels)
    all_area = [ev for ev in (d.normalize_gdacs_feature(f) for f in raw_gdacs)
                if ev and ev["gdacs_type"] in ("FL", "DR") and ev.get("start")]
    slides = [ev for ev in (d.normalize_usgs_feature(f) for f in raw_usgs)
              if ev and ev["hazard"] == "landslide" and ev.get("start")]
    lookup = (lambda g: geometry_for(g, offline)) if with_geometry else None
    groups = d.link_events(all_area, slides, geometry_lookup=lookup) if slides else []
    linked = [(gr["primary"]["id"], r["event"]["id"], r.get("distance_to_area_km"))
              for gr in groups for r in gr["related"] if r["relation"] == "linked"]
    possible = sorted({(gr["primary"]["id"], pl["id"]) for gr in groups
                       if gr["primary"]["source"] == "GDACS" for pl in gr["possible_links"]})
    out.update({
        "usgs_landslide_events": len(slides),
        "linked_pairs": [{"gdacs": a, "usgs": b, "distance_to_area_km": c} for a, b, c in linked],
        "linked_inside_polygon": sum(1 for *_, c in linked if c is not None and c <= 0.0),
        "linked_outside_but_within_buffer": sum(1 for *_, c in linked if c is not None and c > 0.0),
        "possibly_related_pairs": [{"gdacs": a, "usgs": b} for a, b in possible],
    })
    return out


# ---------------------------------------------------------------------------
# E4  Sendai impact rows,  E5  magnitude-0 severities
# ---------------------------------------------------------------------------

def _old_rule(rows) -> Dict[Tuple[str, str], int]:
    """GaiaNet's impact rule before Nov 2026, kept here for comparison:
    the latest row per (indicator, country) by full expires timestamp."""
    best: Dict[Tuple[str, str], Tuple[str, int]] = {}
    for e in rows:
        try:
            v = int(float(str(e.get("sendaivalue")).replace(",", "")))
        except (TypeError, ValueError):
            continue
        k = (d._sendai_label(e), e.get("country") or "Unknown")
        period = e.get("expires_date") or e.get("dateinsert") or ""
        cur = best.get(k)
        if cur is None or period > cur[0] or (period == cur[0] and v > cur[1]):
            best[k] = (period, v)
    return {k: v for k, (_, v) in best.items()}


def e4_impacts(raw_gdacs, offline: bool) -> Dict[str, Any]:
    sig = [f for f in raw_gdacs if ((f.get("properties") or {}).get("alertlevel") or "").lower() in ("orange", "red")]
    events_with_rows, groups, multi = 0, 0, 0
    old_under, old_ratios, naive_over, naive_ratios = 0, [], 0, []
    relabelled = 0
    totals = defaultdict(lambda: {"naive_sum": 0, "old_rule": 0, "new_low": 0, "new_high": 0})
    old_examples, naive_examples = [], []
    for i, f in enumerate(sig, 1):
        p = f.get("properties") or {}
        etype, eid = p.get("eventtype"), p.get("eventid")
        path = DATA_DIR / "details" / f"{etype}_{eid}.json"
        raw = get_json(d.GDACS_EVENT_URL, {"eventtype": etype, "eventid": eid}, path, offline)
        if i % 25 == 0:
            print(f"    details {i}/{len(sig)}")
        if not raw or raw.get("_error") or raw.get("_status") == 204:
            continue
        rows = (raw.get("properties") or {}).get("sendai") or []
        if not rows:
            continue
        events_with_rows += 1
        naive: Dict[Tuple[str, str], int] = defaultdict(int)
        for e in rows:
            try:
                v = int(float(str(e.get("sendaivalue")).replace(",", "")))
            except (TypeError, ValueError):
                continue
            if (e.get("sendainame") or "").strip().lower() == "affected" and d._sendai_label(e) == "Missing / out of contact":
                relabelled += 1
            naive[(d._sendai_label(e), e.get("country") or "Unknown")] += v
        old = _old_rule(rows)
        for r in d.summarize_sendai(rows):
            k = (r["label"], r["country"])
            low, high = r["value"], r["value_high"] or r["value"]
            groups += 1
            multi += r["reports"] > 1
            t = totals[r["label"]]
            t["naive_sum"] += naive[k]; t["old_rule"] += old.get(k, 0); t["new_low"] += low; t["new_high"] += high
            ex = {"event": f"{etype} {eid}", "indicator": r["label"], "country": r["country"], "reports": r["reports"],
                  "old_rule": old.get(k), "new": f"{low:,}" + (f"–{high:,}" if high > low else ""), "naive_sum": naive[k]}
            if old.get(k, 0) < low:
                old_under += 1
                old_ratios.append(low / max(old.get(k, 0), 1))
                old_examples.append(ex)
            if naive[k] > high:
                naive_over += 1
                naive_ratios.append(naive[k] / high if high else float("inf"))
                naive_examples.append(ex)
    old_examples.sort(key=lambda x: -(int(x["new"].split("–")[0].replace(",", "")) / max(x["old_rule"] or 1, 1)))
    naive_examples.sort(key=lambda x: -x["naive_sum"])
    return {
        "orange_red_events": len(sig),
        "events_with_sendai_rows": events_with_rows,
        "indicator_country_groups": groups,
        "groups_from_several_places_or_waves": multi,
        "old_rule_below_largest_single_report": old_under,
        "old_rule_shortfall_ratio": {**_quantiles(old_ratios), "values_are": "largest single report / old rule value"},
        "naive_sum_above_new_high": naive_over,
        "naive_sum_excess_ratio": {**_quantiles(naive_ratios), "values_are": "naive sum / sum of latest per place"},
        "affected_rows_relabelled_missing": relabelled,
        "totals": {k: dict(v) for k, v in totals.items()},
        "old_rule_examples": old_examples[:10],
        "naive_sum_examples": naive_examples[:10],
    }


def e5_magnitude_zero(raw_gdacs) -> Dict[str, Any]:
    area = [f for f in raw_gdacs if (f.get("properties") or {}).get("eventtype") in ("FL", "DR")]
    zero = 0
    for f in area:
        sev = (f.get("properties") or {}).get("severitydata") or {}
        txt = (sev.get("severitytext") or "").strip().lower()
        if sev.get("severity") in (0, 0.0, None) or txt.startswith("magnitude 0"):
            zero += 1
    return {"flood_drought_events": len(area), "magnitude_zero_or_missing": zero}


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _pct(a, b) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def summary_md(res: Dict[str, Any]) -> str:
    L = [f"# GaiaNet hazard evaluation — {res['window']['start']} to {res['window']['end']}", "",
         f"Run at {res['run_at']} · GDACS events {res['counts']['gdacs_events']} · "
         f"USGS events {res['counts']['usgs_events']} · live requests {res['requests']['live']} · "
         f"cached {res['requests']['cached']} · failed {res['requests']['failed']}", ""]
    e1 = res.get("E1")
    if e1:
        rs, og, ref = e1["gaianet_random_sample"], e1["gaianet_orange_red"], e1["reference"]
        L += ["## E1 Earthquake de-duplication",
              f"- GDACS earthquakes: {e1['gdacs_earthquakes']}; USGS earthquakes (M≥{res['usgs_minmag']}): {e1['usgs_earthquakes']}",
              f"- Quakes a dashboard without de-duplication would list twice: {e1['listed_twice_without_dedup']}",
              f"- Reference: GDACS detail records read {ref['details_read']} (sources {ref['sources']}); "
              f"random sample read {ref['random_sample_read']} of {ref['random_sample_requested']} requested; "
              f"source id not in USGS set: {ref['source_id_not_in_usgs_set']}",
              f"- GaiaNet thresholds {e1['gaianet_thresholds']}:",
              f"  - random sample: precision {rs['precision']}, recall {rs['recall']} "
              f"({rs['correct']} correct of {rs['evaluable']}, {rs['predicted']} predicted)",
              f"  - Orange/Red quakes: precision {og['precision']}, recall {og['recall']} "
              f"({og['correct']} correct of {og['evaluable']}, {og['predicted']} predicted)", ""]
        key = "sample" if rs["evaluable"] else "significant"
        rows = [x for x in e1["sensitivity"] if x[key]["precision"] is not None]
        if rows:
            L += [f"Threshold grid on the {'random sample' if key == 'sample' else 'Orange/Red quakes'} "
                  f"(km, h, dMag → precision / recall, matched total):"]
            L += [f"- {x['km']}, {x['h']}, {x['dmag']} → {x[key]['precision']} / {x[key]['recall']}, {x['matched_total']}"
                  for x in rows]
            L += [""]
    e2 = res.get("E2")
    if e2:
        L += ["## E2 Active-now snapshot",
              f"- Taken {e2['taken_at']}; events considered {e2['events_considered']}",
              f"- GaiaNet active: {e2['gaianet_active']} (significant: {e2['gaianet_active_significant']})",
              f"- 'Started in last {NAIVE_RECENT_DAYS} days' rule: {e2['naive_recent_active']} active, of which "
              f"{e2['naive_recent_but_ended']} are over {e2['naive_recent_but_ended_by_reason']}",
              f"- Ongoing events that rule misses: {e2['ongoing_missed_by_naive_recent']} {e2['ongoing_missed_by_hazard']}",
              f"- 'GDACS flag only' rule: {e2['naive_flag_active']} active, of which {e2['naive_flag_but_not_active']} "
              f"are not {e2['naive_flag_but_not_active_by_reason']}", ""]
    e3 = res.get("E3")
    if e3:
        L += ["## E3 Flood/drought location",
              f"- Orange/Red flood+drought events: {e3['orange_red_flood_drought_events']}; with polygon: {e3.get('with_polygon', 'n/a')}",
              f"- Point outside its own affected polygon: {e3.get('point_outside_polygon', 'n/a')} "
              f"({_pct(e3.get('point_outside_polygon', 0), e3.get('with_polygon', 0))})",
              f"- Multi-part polygons: {e3.get('multi_part_polygons', 'n/a')}",
              f"- Farthest affected vertex from the point (km): {e3.get('farthest_affected_vertex_from_point_km')}",
              f"- USGS landslides in window: {e3['usgs_landslide_events']}; linked: {len(e3['linked_pairs'])} "
              f"(outside polygon but within buffer: {e3['linked_outside_but_within_buffer']}); "
              f"possibly related: {len(e3['possibly_related_pairs'])}", ""]
    e4 = res.get("E4")
    if e4:
        L += ["## E4 Impact rows (old rule vs new rule vs naive sum)",
              f"- Orange/Red events: {e4['orange_red_events']}; with Sendai rows: {e4['events_with_sendai_rows']}",
              f"- Indicator×country groups: {e4['indicator_country_groups']}; reported for several places or flood "
              f"waves: {e4['groups_from_several_places_or_waves']}",
              f"- Old rule (latest row per country) below the largest single report: {e4['old_rule_below_largest_single_report']} "
              f"groups; shortfall {e4['old_rule_shortfall_ratio']}",
              f"- Naive sum above the new upper figure: {e4['naive_sum_above_new_high']} groups; "
              f"excess {e4['naive_sum_excess_ratio']}",
              f"- 'Affected' rows that actually report people out of contact: {e4['affected_rows_relabelled_missing']}",
              "- Totals (naive sum / old rule / new low–high):"]
        for lab, t in sorted(e4["totals"].items()):
            L.append(f"  - {lab}: {t['naive_sum']:,} / {t['old_rule']:,} / {t['new_low']:,}–{t['new_high']:,}")
        L += ["- Largest old-rule shortfalls:"] + [f"  - {x}" for x in e4["old_rule_examples"][:6]] + [""]
    e5 = res.get("E5")
    if e5:
        L += ["## E5 'Magnitude 0' severity",
              f"- {e5['magnitude_zero_or_missing']} of {e5['flood_drought_events']} flood/drought records "
              f"({_pct(e5['magnitude_zero_or_missing'], e5['flood_drought_events'])})", ""]
    return "\n".join(L)


def default_window(today: date) -> Tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)                 # last day of previous month
    start = (end.replace(day=1) - timedelta(days=330)).replace(day=1)
    return start, end


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--start"), ap.add_argument("--end")
    ap.add_argument("--offline", action="store_true", help="use cached downloads only")
    ap.add_argument("--no-details", action="store_true", help="skip E4 (one request per Orange/Red event)")
    ap.add_argument("--no-geometry", action="store_true", help="skip polygon downloads in E3")
    ap.add_argument("--usgs-minmag", type=float, default=4.0)
    ap.add_argument("--eq-sample", type=int, default=EQ_SAMPLE_DEFAULT,
                    help="random GDACS earthquakes whose detail record is fetched as reference for E1")
    ap.add_argument("--data-dir", help="read/write downloads here instead of eval/data/hazards")
    ap.add_argument("--now", help=argparse.SUPPRESS)          # tests only
    args = ap.parse_args(argv)

    global DATA_DIR
    if args.data_dir:
        DATA_DIR = Path(args.data_dir)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    start, end = default_window(now.date())
    if args.start:
        start = date.fromisoformat(args.start)
    if args.end:
        end = date.fromisoformat(args.end)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Window {start} .. {end}{' (offline)' if args.offline else ''}")

    print("[1/6] GDACS events (all alert levels)...")
    raw_gdacs = fetch_gdacs(start, end, "green;orange;red", "window", args.offline)
    print("[2/6] USGS earthquakes and landslides...")
    raw_usgs = fetch_usgs(start, end, args.usgs_minmag, "window", args.offline)

    res: Dict[str, Any] = {"run_at": now.isoformat(), "window": {"start": start.isoformat(), "end": end.isoformat()},
                           "usgs_minmag": args.usgs_minmag,
                           "counts": {"gdacs_events": len(raw_gdacs), "usgs_events": len(raw_usgs),
                                      "gdacs_by_type": dict(Counter((f.get("properties") or {}).get("eventtype")
                                                                    for f in raw_gdacs))}}
    print("[3/6] E1 earthquake de-duplication...")
    res["E1"] = e1_earthquakes(raw_gdacs, raw_usgs, args.eq_sample, args.offline)
    print("[4/6] E3 flood/drought location and landslide links...")
    res["E3"] = e3_area_events(raw_gdacs, raw_usgs, args.offline, not args.no_geometry)
    res["E5"] = e5_magnitude_zero(raw_gdacs)
    if not args.no_details:
        print("[5/6] E4 impact rows (one request per Orange/Red event)...")
        res["E4"] = e4_impacts(raw_gdacs, args.offline)
    print("[6/6] E2 active-now snapshot...")
    snap_tag = f"snapshot_{now.date().isoformat()}"
    snap_start = now.date() - timedelta(days=SNAPSHOT_LOOKBACK_DAYS)
    raw_recent = fetch_gdacs(snap_start, now.date(), "green;orange;red", snap_tag, args.offline)
    raw_usgs_recent = fetch_usgs(now.date() - timedelta(days=NAIVE_RECENT_DAYS + 1), now.date(),
                                 DASHBOARD_EQ_MIN_MAG, snap_tag, args.offline)
    if raw_recent or raw_usgs_recent:
        res["E2"] = e2_snapshot(raw_recent, raw_usgs_recent, now)
        with open(RESULTS_DIR / "hazard_snapshots.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(res["E2"]) + "\n")

    res["requests"] = {"live": _stats["live_requests"], "cached": _stats["cache_hits"],
                       "failed": len(_stats["failed"]), "failed_sample": _stats["failed"][:10]}
    stem = f"hazards_{start}_{end}"
    (RESULTS_DIR / f"{stem}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    md = summary_md(res)
    (RESULTS_DIR / f"{stem}_summary.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"Saved: eval/results/{stem}.json and {stem}_summary.md")
    if _stats["failed"]:
        print(f"{len(_stats['failed'])} downloads failed — run the script again to retry them (cached ones are skipped).")
    return res


if __name__ == "__main__":
    main()
