#!/usr/bin/env python3
"""Build data/01_raw/mtr_station_coords.json by joining the official MTR
lines+stations catalogue with OpenStreetMap station coordinates.

The MTR public CSV omits coordinates; OSM has them tagged on the railway
station nodes. We fetch both, normalise station names, and write a small
JSON file keyed by the MTR three-letter Station Code (e.g. HOK, KOW, AIR).

Run once when station coverage changes; commit the JSON. The runtime
exporter (scripts/export_static.py) reads the committed file.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "01_raw" / "mtr_station_coords.json"

MTR_CSV = "https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv"
OVERPASS = "https://overpass-api.de/api/interpreter"
# Two passes: heavy-rail MTR stations are tagged station=subway in OSM, but
# some classic stations only carry railway=station with the MTR operator.
# Union both, keep first-seen per normalised name.
OVERPASS_QUERY = (
    '[out:json][timeout:60];'
    '('
    'node["station"="subway"](22.15,113.8,22.6,114.5);'
    'way ["station"="subway"](22.15,113.8,22.6,114.5);'
    'rel ["station"="subway"](22.15,113.8,22.6,114.5);'
    'node["railway"="station"]["operator"~"MTR",i](22.15,113.8,22.6,114.5);'
    'way ["railway"="station"]["operator"~"MTR",i](22.15,113.8,22.6,114.5);'
    'node["public_transport"="station"]["subway"="yes"](22.15,113.8,22.6,114.5);'
    'way ["public_transport"="station"]["subway"="yes"](22.15,113.8,22.6,114.5);'
    ');out center;'
)

# Manual fixes for stations whose OSM name doesn't normalise to match the
# official MTR English name. Keys are normalised MTR names; values are
# normalised OSM names that mean the same station.
NAME_ALIASES = {
    "hongkong": "hongkong",
    "lohaspark": "lohaspark",
    "easttsimshatsui": "easttsimshatsui",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch_csv(url: str) -> list[dict]:
    with urllib.request.urlopen(url, timeout=60) as resp:
        text = resp.read().decode("utf-8-sig")
    return list(csv.DictReader(StringIO(text)))


def fetch_overpass() -> list[dict]:
    req = urllib.request.Request(
        OVERPASS,
        data=("data=" + urllib.parse.quote(OVERPASS_QUERY)).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "yuutraffic-build/1.0 (https://github.com/yutsang/yuutraffic)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp).get("elements", [])


def main() -> int:
    print("Fetching MTR lines+stations CSV…")
    rows = fetch_csv(MTR_CSV)
    print(f"  {len(rows)} CSV rows.")

    # MTR CSV has duplicate (station_code, English Name) per line/direction.
    # Collapse to unique station_code → display info.
    by_code: dict[str, dict] = {}
    for r in rows:
        code = (r.get("Station Code") or "").strip()
        name_en = (r.get("English Name") or "").strip()
        name_tc = (r.get("Chinese Name") or "").strip()
        if not code:
            continue
        if code not in by_code:
            by_code[code] = {"name_en": name_en, "name_tc": name_tc}

    print(f"  {len(by_code)} unique stations in CSV.")
    print("Querying Overpass for MTR stations with coordinates…")
    elements = fetch_overpass()
    print(f"  {len(elements)} OSM nodes.")

    # Build a normalized-name → (lat, lng) map from OSM. Drop nodes outside
    # the HK SAR (some Shenzhen subway stations leak in via the bbox).
    osm_by_norm: dict[str, tuple[float, float]] = {}
    for el in elements:
        # Nodes have lat/lon directly; ways/relations have a 'center' object
        # because we asked for `out center;`.
        if "lat" in el and "lon" in el:
            lat, lon = float(el["lat"]), float(el["lon"])
        elif "center" in el and el["center"]:
            lat, lon = float(el["center"]["lat"]), float(el["center"]["lon"])
        else:
            continue
        if not (22.15 <= lat <= 22.6 and 113.8 <= lon <= 114.45):
            continue
        tags = el.get("tags", {})
        operator = (tags.get("operator") or "").lower()
        network  = (tags.get("network")  or "").lower()
        # Be permissive: subway-tagged + lat/lng within HK is almost always
        # MTR. Exclude obvious Shenzhen Metro nodes.
        if operator and "shenzhen" in operator: continue
        if network  and "shenzhen" in network:  continue
        name = tags.get("name:en") or tags.get("name") or ""
        name = re.sub(r"\bstation\b", "", name, flags=re.I)
        name = re.sub(r"\bmtr\b",     "", name, flags=re.I)
        key = _norm(name)
        if not key:
            continue
        osm_by_norm.setdefault(key, (lat, lon))

    out: dict[str, dict] = {}
    misses: list[str] = []
    for code, info in by_code.items():
        key = _norm(info["name_en"])
        if key in NAME_ALIASES:
            key = NAME_ALIASES[key]
        coord = osm_by_norm.get(key)
        if not coord:
            misses.append(f"{code} ({info['name_en']})")
            continue
        out[code] = {
            "ne": info["name_en"],
            "nt": info["name_tc"],
            "la": round(coord[0], 6),
            "lg": round(coord[1], 6),
        }

    if misses:
        print(f"WARN: no OSM coord for {len(misses)} stations: {misses}",
              file=sys.stderr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2,
                              sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(out)} stations → {OUT}")
    return 0


if __name__ == "__main__":
    import urllib.parse
    sys.exit(main())
