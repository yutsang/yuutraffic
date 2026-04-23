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
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "01_raw" / "kmb_data.db"
GEO_SRC = ROOT / "data" / "02_intermediate" / "route_geometry"
OUT = ROOT / "web" / "data"
OUT_GEO = OUT / "geometry"

SCHEMA_VERSION = 1


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
                "oe": r["origin_en"] or "",
                "de": r["destination_en"] or "",
                "ot": r["origin_tc"] or "",
                "dt": r["destination_tc"] or "",
                "dirs": sorted(dirs_by_key.get(r["route_key"], [1])),
            }
        )
    return routes


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
            "ne": r["stop_name_en"] or "",
            "nt": r["stop_name_tc"] or "",
            "la": round(float(r["lat"]), 6),
            "lg": round(float(r["lng"]), 6),
            "co": _company_short(r["company"]),
        }
        for r in rows
    }


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
        stops = _export_stops(conn)

    _write_json(OUT / "routes.json", routes)
    _write_json(OUT / "stops.json", stops)

    copied = 0
    if GEO_SRC.exists():
        # Mirror geometry dir. Remove stale files that no longer exist upstream.
        existing = {p.name for p in OUT_GEO.glob("*.json")}
        for src in GEO_SRC.glob("*.json"):
            shutil.copy2(src, OUT_GEO / src.name)
            existing.discard(src.name)
            copied += 1
        for stale in existing:
            (OUT_GEO / stale).unlink(missing_ok=True)

    _write_json(
        OUT / "meta.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "counts": {"routes": len(routes), "stops": len(stops), "geometry": copied},
        },
    )
    print(
        f"Exported {len(routes)} routes, {len(stops)} stops, {copied} geometry files."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
