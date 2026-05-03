#!/usr/bin/env python3
"""Export SQLite + geometry JSONs to static bundles for the GH Pages frontend.

Output layout under ``web/data/``:
    meta.json       - generation timestamp and counts
    routes.json     - searchable route list (all providers)
    stops.json      - stop_id -> {name_en, name_tc, lat, lng, company}
    geometry/*.json - copied from data/02_intermediate/route_geometry/
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "01_raw" / "kmb_data.db"
GEO_SRC = ROOT / "data" / "02_intermediate" / "route_geometry"
OUT = ROOT / "web" / "data"
OUT_GEO = OUT / "geometry"
MTR_COORDS = ROOT / "data" / "01_raw" / "mtr_station_coords.json"
MTR_LINES_CSV_URL = "https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv"
# Macau hand-curated sources. MLM publishes no API and DSAT's bus API is
# CORS-closed + WAF-fenced to HK/MO IPs, so the static port relies on
# locally-edited JSON for now. See data/01_raw/macau_*.json.
MACAU_LRT      = ROOT / "data" / "01_raw" / "macau_lrt.json"
MACAU_BUS      = ROOT / "data" / "01_raw" / "macau_bus.json"
MACAU_SHUTTLES = ROOT / "data" / "01_raw" / "macau_shuttles.json"

SCHEMA_VERSION = 2

# MTR line code → human-readable English / Chinese name.
MTR_LINE_NAMES = {
    "AEL":  ("Airport Express",       "機場快綫"),
    "TCL":  ("Tung Chung Line",       "東涌綫"),
    "TWL":  ("Tsuen Wan Line",        "荃灣綫"),
    "ISL":  ("Island Line",           "港島綫"),
    "KTL":  ("Kwun Tong Line",        "觀塘綫"),
    "TKL":  ("Tseung Kwan O Line",    "將軍澳綫"),
    "EAL":  ("East Rail Line",        "東鐵綫"),
    "TML":  ("Tuen Ma Line",          "屯馬綫"),
    "SIL":  ("South Island Line",     "南港島綫"),
    "DRL":  ("Disneyland Resort Line", "迪士尼綫"),
}

# Tokens kept as-is during title-casing — HK-specific acronyms and station
# line codes. Any alphanumeric token containing digits is kept as well.
PRESERVE_TOKENS = {
    "MTR", "LRT", "HK", "HKIA", "HKU", "HKUST", "CUHK", "UST", "POLYU",
    "GPO", "AEL", "TCL", "TWL", "KTL", "EAL", "ISL", "SIL", "WRL", "DRL",
    "MOL", "SEL", "TCL", "KMB", "LWB", "CTB", "NWFB", "GMB", "UK", "US",
    "HKCEC", "HKIA", "HKIEC", "AIA", "IFC", "PCCW", "AYLC", "IP", "II",
    "III", "IV", "VIP", "MTR", "POS", "YMCA", "YWCA", "HSBC", "ICBC",
}


def _title_case_en(s: str | None) -> str:
    """Convert a HK-style stop/route name to Title Case, preserving acronyms
    and alphanumeric codes.

    Examples:
        "ON TAI ESTATE (AN640)" → "On Tai Estate (AN640)"
        "MTR HUNG HOM STATION"  → "MTR Hung Hom Station"
        "Central (Macao Ferry)" → "Central (Macao Ferry)" (already ok)
    """
    if not s:
        return s
    tokens = re.split(r"(\s+|[()/-])", s)
    out: list[str] = []
    for t in tokens:
        if not t or t.isspace() or t in "()/-":
            out.append(t)
            continue
        if re.search(r"\d", t):  # codes like AN640, TN951, 2A
            out.append(t)
            continue
        upper = t.upper()
        if upper in PRESERVE_TOKENS:
            out.append(upper)
            continue
        # .capitalize() handles "JOHN'S" → "John's" natively.
        out.append(t.capitalize())
    return "".join(out)


def _clean_mtrb_label(s: str | None) -> str:
    """MTR Bus origin/destination strings come pre-decorated by the data
    updater as 'ROUTE · STOP_CODE — DISTRICT' because the official MTR Bus
    API doesn't expose stop names. Keep just the human-readable district
    half (after the em-dash) so the route card reads cleanly."""
    if not s:
        return s or ""
    m = re.search(r"—\s*(.+?)\s*$", s)
    return m.group(1) if m else s


def _company_short(company: str | None) -> str:
    c = (company or "").upper()
    if "KMB" in c or "LWB" in c:
        return "KMB"
    if "CTB" in c or "CITYBUS" in c:
        return "CTB"
    if "GMB" in c or ("GREEN" in c and "MINIBUS" in c):
        return "GMB"
    if "MTR" in c and "BUS" in c:
        return "MTRB"
    if "RMB" in c or ("RED" in c and "MINIBUS" in c):
        return "RMB"
    return "KMB"


def _fetch_kmb_route_variants() -> dict[tuple[str, int, int], dict]:
    """Fetch KMB's full route catalogue so we know origin/destination per
    service_type variant — the DB's `routes` table stores only one row per
    route_key so variant info was being lost (e.g., 219X service_type 1 has
    origin "Laguna City" while service_type 4 has origin "Ko Ling Road").

    Returns: {(route_id, service_type, direction): {oe, de, ot, dt}}
    """
    url = "https://data.etabus.gov.hk/v1/transport/kmb/route/"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"WARN: KMB /route/ fetch failed ({e}); variant names may be incorrect.",
              file=sys.stderr)
        return {}
    out: dict[tuple[str, int, int], dict] = {}
    for entry in data.get("data", []):
        rid = entry.get("route")
        bound = entry.get("bound")
        try:
            st = int(entry.get("service_type") or 1)
        except (TypeError, ValueError):
            st = 1
        direction = 1 if bound == "O" else 2
        out[(rid, st, direction)] = {
            "oe": entry.get("orig_en", ""),
            "de": entry.get("dest_en", ""),
            "ot": entry.get("orig_tc", ""),
            "dt": entry.get("dest_tc", ""),
        }
    return out


def _export_routes(conn: sqlite3.Connection) -> list[dict]:
    """Emit one route entry per distinct (route_key, service_type) variant.

    KMB routes commonly have several service_types with different origins
    (e.g., peak-hour extras from a different depot). Previously the exporter
    used only the `routes` table — which stores one row per route_key — and
    therefore collapsed all variants to whatever service_type was inserted
    last. We now query `route_stops` (which DOES distinguish service_type)
    and overlay variant-specific origin/destination names from the live KMB
    catalogue.
    """
    base_rows = conn.execute(
        """
        SELECT route_key, route_id, origin_en, destination_en,
               origin_tc, destination_tc, service_type, company,
               provider_route_id
        FROM routes
        """
    ).fetchall()
    base_by_key = {r["route_key"]: dict(r) for r in base_rows}

    # (route_key, service_type, direction) distinct combinations
    variant_rows = conn.execute(
        """
        SELECT route_key, COALESCE(service_type, 1) AS st, direction
        FROM route_stops
        WHERE route_key IS NOT NULL
        GROUP BY route_key, st, direction
        """
    ).fetchall()

    # For each (route_key, service_type), collect directions
    variants_dirs: dict[tuple[str, int], list[int]] = defaultdict(list)
    for v in variant_rows:
        variants_dirs[(v["route_key"], int(v["st"]))].append(int(v["direction"]))

    kmb_variants = _fetch_kmb_route_variants()

    routes: list[dict] = []
    for (rk, st), dirs in variants_dirs.items():
        base = base_by_key.get(rk, {})
        company = _company_short(base.get("company"))
        route_id = base.get("route_id") or rk.split("_", 1)[-1]

        # Variant-specific origin/destination. For KMB, pick the variant-
        # matching row from the live catalogue; for other operators, fall
        # back to whatever the routes table has.
        oe = base.get("origin_en", "") or ""
        de = base.get("destination_en", "") or ""
        ot = base.get("origin_tc", "") or ""
        dt = base.get("destination_tc", "") or ""
        if company == "KMB" and kmb_variants:
            # Try to match on the outbound direction first (more common).
            for d in sorted(dirs):
                meta = kmb_variants.get((route_id, st, d))
                if meta:
                    oe, de = meta["oe"], meta["de"]
                    ot, dt = meta["ot"], meta["dt"]
                    break

        if company == "MTRB":
            oe = _clean_mtrb_label(oe)
            de = _clean_mtrb_label(de)
            ot = _clean_mtrb_label(ot)
            dt = _clean_mtrb_label(dt)
        routes.append({
            "rk": rk,
            "id": route_id,
            "co": company,
            "st": st,
            "pid": base.get("provider_route_id", "") or "",
            "oe": _title_case_en(oe),
            "de": _title_case_en(de),
            "ot": ot,
            "dt": dt,
            "dirs": sorted(set(dirs)),
        })
    routes.sort(key=lambda r: (r["co"], r["id"], r["st"]))
    return routes


def _route_stop_sets(conn: sqlite3.Connection) -> dict[tuple[str, int], set[tuple[int, int]]]:
    """Map each (route_key, service_type) to the set of stop COORDINATES it
    serves, rounded to ~11 m (4 decimal places). KMB and Citybus maintain
    independent stop_id registries, so a joint route (e.g., 101 or 621)
    looks like two completely disjoint sets when keyed by stop_id. Comparing
    coordinates fixes that — buses physically stop at the same kerb and the
    coordinates from each operator's API agree to a few metres.
    """
    rows = conn.execute(
        """
        SELECT rs.route_key, COALESCE(rs.service_type, 1) AS st,
               s.lat AS lat, s.lng AS lng
        FROM route_stops rs
        JOIN stops s ON s.stop_id = rs.stop_id
        WHERE rs.route_key IS NOT NULL
          AND s.lat IS NOT NULL AND s.lng IS NOT NULL
        """
    ).fetchall()
    out: dict[tuple[str, int], set[tuple[int, int]]] = defaultdict(set)
    for r in rows:
        # Round to a ≈ 50 m grid. KMB and Citybus publish stop coords for
        # the same physical kerb that differ by 10–40 m (one uses the
        # entrance, the other the road centreline). 4dp (≈ 11 m) was too
        # tight; 3dp (≈ 110 m) risks matching unrelated nearby stops.
        # Use a grid sized between them.
        key = (int(round(float(r["lat"]) * 2000)),
               int(round(float(r["lng"]) * 2000)))
        out[(r["route_key"], int(r["st"]))].add(key)
    return dict(out)


def _merge_joint_routes(
    routes: list[dict], stop_sets: dict[tuple[str, int], set[tuple[int, int]]]
) -> list[dict]:
    """Collapse jointly-operated routes (e.g. KMB+CTB 101 or 621) into one
    entry. The stop_sets values are sets of rounded (lat, lng) tuples so
    operators with independent stop registries can still be matched.

    Grouped by (route_id, service_type). Jaccard overlap ≥ 0.5 qualifies as
    joint; KMB 1 (Kowloon) vs Citybus 1 (HK Island) have ~0 overlap so they
    stay separate.
    """
    # Calibrated empirically: with the ~50 m grid above, genuine joints
    # (101, 621, 182…) score ~0.45 while same-number unrelated routes
    # (KMB 1 vs CTB 1) score 0. 0.3 is comfortably between the two.
    JACCARD_THRESHOLD = 0.3

    by_variant: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in routes:
        by_variant[(r["id"], r["st"])].append(r)

    merged: list[dict] = []
    for group in by_variant.values():
        companies = {r["co"] for r in group}
        if len(companies) == 1:
            merged.extend(group)
            continue

        all_stops: set[str] = set()
        shared: set[str] | None = None
        for r in group:
            s = stop_sets.get((r["rk"], r["st"]), set())
            all_stops |= s
            shared = s if shared is None else (shared & s)
        jaccard = (len(shared or set()) / len(all_stops)) if all_stops else 0.0

        if jaccard < JACCARD_THRESHOLD:
            merged.extend(group)
            continue

        primary_co = "KMB" if "KMB" in companies else sorted(companies)[0]
        primary = dict(next(r for r in group if r["co"] == primary_co))
        partners = [
            {"co": r["co"], "rk": r["rk"], "id": r["id"],
             "pid": r["pid"], "st": r["st"]}
            for r in group
        ]
        partners.sort(key=lambda p: (p["co"] != primary_co, p["co"]))
        primary["partners"] = partners
        merged.append(primary)

    merged.sort(key=lambda r: (r["co"], r["id"], r["st"]))
    return merged


def _export_stops(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT stop_id, stop_name_en, stop_name_tc, lat, lng, company
        FROM stops
        WHERE lat IS NOT NULL AND lng IS NOT NULL
        """
    ).fetchall()
    return {
        r["stop_id"]: {
            "ne": _title_case_en(r["stop_name_en"] or ""),
            "nt": r["stop_name_tc"] or "",
            "la": round(float(r["lat"]), 6),
            "lg": round(float(r["lng"]), 6),
            "co": _company_short(r["company"]),
        }
        for r in rows
    }


def _fetch_mtr_csv() -> list[dict]:
    """Fetch the public MTR lines+stations CSV. Returns rows with keys
    `Line Code`, `Direction` (UT/DT), `Station Code`, `Sequence`,
    `English Name`, `Chinese Name`. Empty list on network failure (so the
    rest of the export still completes)."""
    import csv
    from io import StringIO
    try:
        with urllib.request.urlopen(MTR_LINES_CSV_URL, timeout=30) as resp:
            text = resp.read().decode("utf-8-sig")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"WARN: MTR CSV fetch failed ({e}); MTR rail will be skipped.",
              file=sys.stderr)
        return []
    return list(csv.DictReader(StringIO(text)))


def _load_mtr_coords() -> dict[str, dict]:
    if not MTR_COORDS.exists():
        return {}
    return json.loads(MTR_COORDS.read_text(encoding="utf-8"))


def _build_mtr(
    routes: list[dict], stops: dict[str, dict],
    stop_routes: dict[str, list[str]],
) -> tuple[list[dict], list[Path]]:
    """Add MTR rail routes/stations into the existing exports and return the
    list of geometry file paths written (so the caller can include them in
    the up-to-date set when pruning)."""
    csv_rows = _fetch_mtr_csv()
    if not csv_rows:
        return [], []
    coords = _load_mtr_coords()
    if not coords:
        print("WARN: data/01_raw/mtr_station_coords.json missing; "
              "run scripts/build_mtr_coords.py to regenerate.", file=sys.stderr)
        return [], []

    # Insert station stops keyed by 'MTR_<code>' so they don't collide with
    # bus stop_ids (which are alphanumeric hex hashes).
    for code, c in coords.items():
        stops[f"MTR_{code}"] = {
            "ne": c["ne"],
            "nt": c["nt"],
            "la": c["la"],
            "lg": c["lg"],
            "co": "MTR",
        }

    # Group rows by (line, direction). Each (line, direction) is one route in
    # routes.json; both directions share the same route_key with d=1 / d=2.
    by_line_dir: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in csv_rows:
        line = (r.get("Line Code") or "").strip()
        bound = (r.get("Direction") or "").strip().upper()
        # MTR uses UP/DT; some rows specify UT/DT for the few stations that
        # only run in one direction on a particular leg. Treat anything
        # starting with U or D as up/down.
        if not line or not bound:
            continue
        d = 1 if bound.startswith("U") or bound == "UP" else 2
        by_line_dir[(line, d)].append(r)

    geo_paths: list[Path] = []
    routes_added: dict[str, dict] = {}

    for (line, d), rows in by_line_dir.items():
        rows.sort(key=lambda x: float(x.get("Sequence") or 0))
        if not rows:
            continue
        first, last = rows[0], rows[-1]
        rk = f"MTR_{line}"
        en, tc = MTR_LINE_NAMES.get(line, (line, line))
        oe = first.get("English Name", "")
        de = last.get("English Name", "")
        ot = first.get("Chinese Name", "")
        dt = last.get("Chinese Name", "")

        if rk not in routes_added:
            routes_added[rk] = {
                "rk": rk,
                "id": line,
                "co": "MTR",
                "st": 1,
                "pid": "",
                "oe": _title_case_en(en),
                "de": "",
                "ot": tc,
                "dt": "",
                "dirs": [],
            }
        entry = routes_added[rk]
        if d not in entry["dirs"]:
            entry["dirs"].append(d)
            entry["dirs"].sort()
        # Direction 1's origin/dest become the "outbound" terminus pair.
        if d == 1:
            entry["oe"] = _title_case_en(oe)
            entry["de"] = _title_case_en(de)
            entry["ot"] = ot
            entry["dt"] = dt

        # Geometry: list of station stops + a polyline that just connects
        # them in order. No OSRM routing for trains — they don't follow
        # roads anyway.
        geo_stops = []
        coords_line = []
        for i, r in enumerate(rows, start=1):
            code = (r.get("Station Code") or "").strip()
            sc = coords.get(code, {})
            if not sc:
                continue
            geo_stops.append({
                "stop_id": f"MTR_{code}",
                "stop_name": _title_case_en(r.get("English Name", "")),
                "stop_name_tc": r.get("Chinese Name", ""),
                "sequence": i,
                "company": "MTR",
                "lat": sc["la"],
                "lng": sc["lg"],
                # Carry the raw 3-letter code so the client can build the
                # MTR ETA URL without remapping.
                "mtr_code": code,
                "mtr_line": line,
            })
            coords_line.append([sc["la"], sc["lg"]])

        # Update reverse index so 'Near me' can return MTR routes too.
        for s in geo_stops:
            stop_routes.setdefault(s["stop_id"], []).append(rk)

        # Write geometry file.
        out_path = OUT_GEO / f"{rk}_{d}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({
                "route_key": rk,
                "direction": d,
                "company": "MTR",
                "line": line,
                "stops": geo_stops,
                "coords": coords_line,
            }, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        geo_paths.append(out_path)

    routes.extend(routes_added.values())
    return list(routes_added.values()), geo_paths


def _export_stop_routes(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """For each stop_id, the list of route_keys serving it.

    Used by the browser's 'Near me' flow to discover which routes run at
    the stops nearest the user without having to download every per-route
    geometry file.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT stop_id, route_key
        FROM route_stops
        WHERE stop_id IS NOT NULL AND route_key IS NOT NULL
        """
    ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["stop_id"], []).append(r["route_key"])
    for v in out.values():
        v.sort()
    return out


def _build_macau_lrt(
    routes: list[dict], stops: dict[str, dict],
    stop_routes: dict[str, list[str]],
) -> list[Path]:
    """Inject MLM Light Rapid Transit data from data/01_raw/macau_lrt.json
    into the export bundles.

    Schema mirrors the MTR pipeline: each line becomes one route entry with
    co='LRT'; each station becomes a stop keyed 'LRT_<code>'; geometry files
    are written under web/data/geometry/<rk>_1.json.
    """
    if not MACAU_LRT.exists():
        return []
    raw = json.loads(MACAU_LRT.read_text(encoding="utf-8"))
    stations = raw.get("stations", {})
    lines    = raw.get("lines", [])

    for code, s in stations.items():
        stops[f"LRT_{code}"] = {
            "ne": s["ne"],
            "nt": s["nt"],
            "la": float(s["la"]),
            "lg": float(s["lg"]),
            "co": "LRT",
        }

    geo_paths: list[Path] = []
    for line in lines:
        line_id = line["id"]
        rk = f"LRT_{line_id}"
        codes = line.get("stations", [])
        if not codes:
            continue
        first = stations.get(codes[0], {})
        last  = stations.get(codes[-1], {})

        routes.append({
            "rk": rk,
            "id": line_id,
            "co": "LRT",
            "st": 1,
            "pid": "",
            "oe": _title_case_en(line.get("name_en", line_id)),
            "de": "",
            "ot": line.get("name_tc", line_id),
            "dt": "",
            "color": line.get("color", "#0091da"),
            "termini_en": [first.get("ne", ""), last.get("ne", "")],
            "termini_tc": [first.get("nt", ""), last.get("nt", "")],
            "dirs": [1],
        })

        geo_stops = []
        coords_line = []
        for i, code in enumerate(codes, start=1):
            s = stations.get(code)
            if not s:
                continue
            stop_id = f"LRT_{code}"
            geo_stops.append({
                "stop_id": stop_id,
                "stop_name": s["ne"],
                "stop_name_tc": s["nt"],
                "sequence": i,
                "company": "LRT",
                "lat": float(s["la"]),
                "lng": float(s["lg"]),
                "lrt_code": code,
                "lrt_line": line_id,
            })
            coords_line.append([float(s["la"]), float(s["lg"])])
            stop_routes.setdefault(stop_id, []).append(rk)

        out_path = OUT_GEO / f"{rk}_1.json"
        out_path.write_text(
            json.dumps({
                "route_key": rk,
                "direction": 1,
                "company": "LRT",
                "line": line_id,
                "color": line.get("color", "#0091da"),
                "stops": geo_stops,
                "coords": coords_line,
            }, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        geo_paths.append(out_path)
    return geo_paths


def _build_macau_bus(
    routes: list[dict], stops: dict[str, dict],
    stop_routes: dict[str, list[str]],
) -> list[Path]:
    """Inject the seed DSAT bus catalogue from data/01_raw/macau_bus.json.

    The full DSAT API needs HK/MO IP access; until scripts/build_macau_bus.py
    exists this file is the only source for MOBus routes.
    """
    if not MACAU_BUS.exists():
        return []
    raw = json.loads(MACAU_BUS.read_text(encoding="utf-8"))
    macau_stops = raw.get("stops", {})
    macau_routes = raw.get("routes", [])

    for stop_id, s in macau_stops.items():
        stops[stop_id] = {
            "ne": s["ne"],
            "nt": s["nt"],
            "la": float(s["la"]),
            "lg": float(s["lg"]),
            "co": "MOB",
        }

    geo_paths: list[Path] = []
    for r in macau_routes:
        rid = r["id"]
        rk = f"MOB_{rid}"
        seq = r.get("stops_outbound", [])
        if not seq:
            continue
        first = macau_stops.get(seq[0], {})
        last  = macau_stops.get(seq[-1], {})

        # DSAT circular routes have first == last stop. Their canonical name
        # ("關閘 - 媽閣") encodes the two real endpoints — split on " - " or
        # " ↔ " to recover them when the stop names alone would just say
        # "關閘總站 → 關閘總站".
        oe = _title_case_en(first.get("ne", ""))
        de = _title_case_en(last.get("ne", ""))
        ot = first.get("nt", "")
        dt = last.get("nt", "")
        nm = r.get("name_en") or r.get("name_tc") or ""
        if seq[0] == seq[-1] and nm:
            parts = re.split(r"\s*[-↔→]\s*", nm, maxsplit=1)
            if len(parts) == 2 and parts[0] and parts[1]:
                oe, de = _title_case_en(parts[0]), _title_case_en(parts[1])
                ot, dt = parts[0], parts[1]

        routes.append({
            "rk": rk,
            "id": rid,
            "co": "MOB",
            "st": 1,
            "pid": r.get("operator", ""),
            "oe": oe,
            "de": de,
            "ot": ot,
            "dt": dt,
            "operator_tc": r.get("operator_tc", ""),
            "frequency": r.get("frequency", ""),
            "hours": r.get("hours", ""),
            "dirs": [1],
        })

        geo_stops = []
        coords_line = []
        for i, sid in enumerate(seq, start=1):
            s = macau_stops.get(sid)
            if not s:
                continue
            geo_stops.append({
                "stop_id": sid,
                "stop_name": s["ne"],
                "stop_name_tc": s["nt"],
                "sequence": i,
                "company": "MOB",
                "lat": float(s["la"]),
                "lng": float(s["lg"]),
            })
            coords_line.append([float(s["la"]), float(s["lg"])])
            stop_routes.setdefault(sid, []).append(rk)

        out_path = OUT_GEO / f"{rk}_1.json"
        out_path.write_text(
            json.dumps({
                "route_key": rk,
                "direction": 1,
                "company": "MOB",
                "stops": geo_stops,
                "coords": coords_line,
            }, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        geo_paths.append(out_path)
    return geo_paths


def _build_macau_shuttles(
    routes: list[dict], stops: dict[str, dict],
    stop_routes: dict[str, list[str]],
) -> list[Path]:
    """Casino shuttle (發財車) routes — short, free shuttles between casinos
    and transit hubs (ferry terminals, border gate, airport, HZMB port).
    """
    if not MACAU_SHUTTLES.exists():
        return []
    raw = json.loads(MACAU_SHUTTLES.read_text(encoding="utf-8"))
    sc_stops = raw.get("stops", {})
    sc_routes = raw.get("routes", [])

    for code, s in sc_stops.items():
        stop_id = f"MOSC_{code}"
        stops[stop_id] = {
            "ne": s["ne"],
            "nt": s["nt"],
            "la": float(s["la"]),
            "lg": float(s["lg"]),
            "co": "MOSC",
        }

    geo_paths: list[Path] = []
    for r in sc_routes:
        rid = r["id"]
        rk = f"MOSC_{rid}"
        from_code = r["from"]
        to_code   = r["to"]
        from_s = sc_stops.get(from_code)
        to_s   = sc_stops.get(to_code)
        if not from_s or not to_s:
            continue

        routes.append({
            "rk": rk,
            "id": rid,
            "co": "MOSC",
            "st": 1,
            "pid": r.get("casino", ""),
            "oe": _title_case_en(from_s["ne"]),
            "de": _title_case_en(to_s["ne"]),
            "ot": from_s["nt"],
            "dt": to_s["nt"],
            "casino": r.get("casino", ""),
            "color": r.get("color", "#a89060"),
            "frequency": r.get("frequency", ""),
            "hours": r.get("hours", ""),
            "dirs": [1],
        })

        geo_stops = [
            {"stop_id": f"MOSC_{from_code}", "stop_name": from_s["ne"],
             "stop_name_tc": from_s["nt"], "sequence": 1, "company": "MOSC",
             "lat": float(from_s["la"]), "lng": float(from_s["lg"])},
            {"stop_id": f"MOSC_{to_code}",   "stop_name": to_s["ne"],
             "stop_name_tc": to_s["nt"],   "sequence": 2, "company": "MOSC",
             "lat": float(to_s["la"]),   "lng": float(to_s["lg"])},
        ]
        coords_line = [
            [float(from_s["la"]), float(from_s["lg"])],
            [float(to_s["la"]),   float(to_s["lg"])],
        ]
        stop_routes.setdefault(f"MOSC_{from_code}", []).append(rk)
        stop_routes.setdefault(f"MOSC_{to_code}",   []).append(rk)

        out_path = OUT_GEO / f"{rk}_1.json"
        out_path.write_text(
            json.dumps({
                "route_key": rk,
                "direction": 1,
                "company": "MOSC",
                "casino": r.get("casino", ""),
                "color": r.get("color", "#a89060"),
                "stops": geo_stops,
                "coords": coords_line,
            }, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        geo_paths.append(out_path)
    return geo_paths


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def _write_empty() -> None:
    _write_json(OUT / "routes.json", [])
    _write_json(OUT / "stops.json", {})
    _write_json(
        OUT / "meta.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "counts": {"routes": 0, "stops": 0},
            "empty": True,
        },
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    OUT_GEO.mkdir(parents=True, exist_ok=True)

    if not DB.exists() or DB.stat().st_size == 0:
        if "--allow-empty" in sys.argv:
            print("WARN: DB empty; writing empty bundles.", file=sys.stderr)
            _write_empty()
            return 0
        print(
            f"ERROR: DB missing or empty at {DB}. Run `yuutraffic --update` first,",
            file=sys.stderr,
        )
        print("       or pass --allow-empty to write placeholder bundles.", file=sys.stderr)
        return 1

    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        routes = _export_routes(conn)
        stop_sets = _route_stop_sets(conn)
        routes = _merge_joint_routes(routes, stop_sets)
        stops = _export_stops(conn)
        stop_routes = _export_stop_routes(conn)

    copied = 0
    fresh: set[str] = set()
    if GEO_SRC.exists():
        for src in GEO_SRC.glob("*.json"):
            with open(src, encoding="utf-8") as f:
                g = json.load(f)
            for s in g.get("stops", []) or []:
                if "stop_name" in s and s["stop_name"]:
                    s["stop_name"] = _title_case_en(s["stop_name"])
            with open(OUT_GEO / src.name, "w", encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False, separators=(",", ":"))
            fresh.add(src.name)
            copied += 1

    # MTR rail (added after bus geometry so its files survive the prune below).
    mtr_routes, mtr_paths = _build_mtr(routes, stops, stop_routes)
    for p in mtr_paths:
        fresh.add(p.name)

    # Macau modes — all hand-curated since DSAT/MLM publish no open API and
    # casino shuttles aren't APIs at all.
    lrt_paths = _build_macau_lrt(routes, stops, stop_routes)
    bus_paths = _build_macau_bus(routes, stops, stop_routes)
    sc_paths  = _build_macau_shuttles(routes, stops, stop_routes)
    for p in (*lrt_paths, *bus_paths, *sc_paths):
        fresh.add(p.name)

    _write_json(OUT / "routes.json", routes)
    _write_json(OUT / "stops.json", stops)
    _write_json(OUT / "stop_routes.json", stop_routes)

    # Prune any files no longer regenerated this run.
    OUT_GEO.mkdir(parents=True, exist_ok=True)
    for p in OUT_GEO.glob("*.json"):
        if p.name not in fresh:
            p.unlink(missing_ok=True)

    _write_json(
        OUT / "meta.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "counts": {
                "routes": len(routes),
                "stops": len(stops),
                "stop_routes": len(stop_routes),
                "geometry": copied + len(mtr_paths) + len(lrt_paths) + len(bus_paths) + len(sc_paths),
                "mtr_lines": len(mtr_routes),
                "macau_lrt": len(lrt_paths),
                "macau_bus": len(bus_paths),
                "macau_shuttles": len(sc_paths),
            },
        },
    )
    print(
        f"Exported {len(routes)} routes, {len(stops)} stops, "
        f"{copied + len(mtr_paths) + len(lrt_paths) + len(bus_paths) + len(sc_paths)} geometry files "
        f"(macau: {len(lrt_paths)} lrt + {len(bus_paths)} bus + {len(sc_paths)} shuttles)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
