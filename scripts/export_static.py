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
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "01_raw" / "kmb_data.db"
GEO_SRC = ROOT / "data" / "02_intermediate" / "route_geometry"
OUT = ROOT / "web" / "data"
OUT_GEO = OUT / "geometry"

SCHEMA_VERSION = 2

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


def _export_routes(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT route_key, route_id, origin_en, destination_en,
               origin_tc, destination_tc, service_type, company,
               provider_route_id
        FROM routes
        ORDER BY company, route_id
        """
    ).fetchall()
    dir_rows = conn.execute(
        "SELECT route_key, direction FROM route_stops GROUP BY route_key, direction"
    ).fetchall()
    dirs_by_key: dict[str, list[int]] = {}
    for row in dir_rows:
        dirs_by_key.setdefault(row["route_key"], []).append(int(row["direction"]))

    routes: list[dict] = []
    for r in rows:
        routes.append(
            {
                "rk": r["route_key"],
                "id": r["route_id"],
                "co": _company_short(r["company"]),
                "st": r["service_type"] or 1,
                "pid": r["provider_route_id"] or "",
                "oe": _title_case_en(r["origin_en"] or ""),
                "de": _title_case_en(r["destination_en"] or ""),
                "ot": r["origin_tc"] or "",
                "dt": r["destination_tc"] or "",
                "dirs": sorted(dirs_by_key.get(r["route_key"], [1])),
            }
        )
    return routes


def _merge_joint_routes(routes: list[dict]) -> list[dict]:
    """Collapse KMB+CTB (or other cross-operator) joint services into a single
    entry. Hong Kong has many cooperated routes (e.g. 101, 102, 112) where both
    operators run the same route number between the same termini.

    Policy: group by (route_id, normalized origin, normalized destination).
    If a group has multiple operators, keep the KMB entry as primary (or the
    alphabetically-first operator if no KMB) and attach the others as
    `partners`. The client fetches ETA from every partner and merges.
    """
    def norm(s: str) -> str:
        return re.sub(r"\W+", " ", (s or "").upper()).strip()

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in routes:
        groups[(r["id"], norm(r["oe"]), norm(r["de"]))].append(r)

    merged: list[dict] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        by_co: dict[str, list[dict]] = defaultdict(list)
        for r in group:
            by_co[r["co"]].append(r)
        if len(by_co) == 1:
            merged.extend(group)
            continue
        primary_co = "KMB" if "KMB" in by_co else sorted(by_co)[0]
        primary = dict(by_co[primary_co][0])
        partners = [
            {"co": e["co"], "rk": e["rk"], "id": e["id"],
             "pid": e["pid"], "st": e["st"]}
            for entries in by_co.values()
            for e in entries
        ]
        partners.sort(key=lambda p: (p["co"] != primary_co, p["co"]))
        primary["partners"] = partners
        merged.append(primary)
    merged.sort(key=lambda r: (r["co"], r["id"]))
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
        routes = _merge_joint_routes(routes)
        stops = _export_stops(conn)
        stop_routes = _export_stop_routes(conn)

    _write_json(OUT / "routes.json", routes)
    _write_json(OUT / "stops.json", stops)
    _write_json(OUT / "stop_routes.json", stop_routes)

    copied = 0
    if GEO_SRC.exists():
        existing = {p.name for p in OUT_GEO.glob("*.json")}
        for src in GEO_SRC.glob("*.json"):
            # Read-modify-write instead of shutil.copy2 so we can title-case
            # stop_name while we're at it. Pretty-printing is skipped for size.
            with open(src, encoding="utf-8") as f:
                g = json.load(f)
            for s in g.get("stops", []) or []:
                if "stop_name" in s and s["stop_name"]:
                    s["stop_name"] = _title_case_en(s["stop_name"])
            with open(OUT_GEO / src.name, "w", encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False, separators=(",", ":"))
            existing.discard(src.name)
            copied += 1
        for stale in existing:
            (OUT_GEO / stale).unlink(missing_ok=True)

    _write_json(
        OUT / "meta.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "counts": {
                "routes": len(routes),
                "stops": len(stops),
                "stop_routes": len(stop_routes),
                "geometry": copied,
            },
        },
    )
    print(
        f"Exported {len(routes)} routes, {len(stops)} stops, {copied} geometry files."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
