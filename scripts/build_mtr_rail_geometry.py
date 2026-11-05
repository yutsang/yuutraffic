#!/usr/bin/env python3
"""Build per-line MTR rail track geometry from OpenStreetMap via Overpass.

The static export pipeline (``scripts/export_static.py``) previously chained
station coordinates with ``L.polyline`` for MTR lines, producing visibly
straight segments that don't follow the actual rail alignment. Trains don't
follow roads, so OSRM road routing isn't useful — but OSM's railway ways
contain the real track geometry tagged with each line's ``ref``/``name``.

For each MTR line we ask Overpass for the matching ``route=subway`` (or
``route=light_rail`` for branches) relation, then concatenate the ordered
``way`` member geometries into a single polyline. Output:

    data/02_intermediate/mtr_rail_geometry/{line_id}.json
        {"coords": [[lat, lng], ...], "source": "osm-overpass"}

Run once per geometry refresh (script is idempotent). Failures are tolerated
— ``export_static.py`` falls back to the straight-line connector for any
line whose JSON is missing or has fewer than 10 points.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "02_intermediate" / "mtr_rail_geometry"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "YuuTraffic/1.0"

# Overpass nominally allows 1 query per ~2 s burst on the public endpoint.
THROTTLE_SECONDS = 2.0

# Per-line query strategy. We try several queries in order until one returns
# a relation with ways. Some MTR lines are tagged route=subway, others (like
# East Rail and Tuen Ma which run above ground for most of their length) are
# tagged route=train or route=light_rail.
#
# Each entry is a list of Overpass query bodies (without the [out:json]
# wrapper). The first one that returns a relation with member ways wins.
LINE_QUERIES: dict[str, list[str]] = {
    "AEL": [
        'relation["route"~"subway|train|light_rail"]["ref"="AEL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"Airport Express",i];',
    ],
    "TCL": [
        'relation["route"~"subway|train|light_rail"]["ref"="TCL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"Tung Chung",i];',
    ],
    "TWL": [
        'relation["route"~"subway|train|light_rail"]["ref"="TWL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"Tsuen Wan",i];',
    ],
    "ISL": [
        'relation["route"~"subway|train|light_rail"]["ref"="ISL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"Island Line",i];',
    ],
    "KTL": [
        'relation["route"~"subway|train|light_rail"]["ref"="KTL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"Kwun Tong",i];',
    ],
    "TKL": [
        'relation["route"~"subway|train|light_rail"]["ref"="TKL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"Tseung Kwan O",i];',
    ],
    "EAL": [
        'relation["route"~"subway|train|light_rail"]["ref"="EAL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"East Rail",i];',
    ],
    "TML": [
        'relation["route"~"subway|train|light_rail"]["ref"="TML"];',
        'relation["route"~"subway|train|light_rail"]["name"~"Tuen Ma",i];',
    ],
    "SIL": [
        'relation["route"~"subway|train|light_rail"]["ref"="SIL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"South Island",i];',
    ],
    "DRL": [
        'relation["route"~"subway|train|light_rail"]["ref"="DRL"];',
        'relation["route"~"subway|train|light_rail"]["name"~"Disneyland",i];',
    ],
}


def _overpass(query_body: str) -> dict:
    """POST a single Overpass query body. Returns parsed JSON or {}."""
    full = f"[out:json][timeout:120];({query_body});out geom;"
    data = urllib.parse.urlencode({"data": full}).encode("utf-8")
    req = urllib.request.Request(
        OVERPASS,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"  WARN: Overpass query failed: {e}", file=sys.stderr)
        return {}


def _extract_ways(elements: list[dict]) -> list[list[tuple[float, float]]]:
    """Return a list of unique way coordinate sequences across all returned
    relations. MTR lines are typically split into multiple direction-specific
    sub-relations in OSM (one per leg, plus overall up/down); naively
    concatenating every member would duplicate every way many times over and
    introduce huge "leaps" between disjoint sections in the stitched output.

    De-duplicating by way ``ref`` (Overpass returns ``ref`` on each member
    pointing to the underlying way's id) collapses parallel sub-relations
    into one set of unique ways which can then be ordered geometrically.
    """
    seen: set[int] = set()
    ways: list[list[tuple[float, float]]] = []
    for el in elements:
        if el.get("type") != "relation":
            continue
        for m in el.get("members", []) or []:
            if m.get("type") != "way":
                continue
            # Skip platform/station polygons; we only want rail track.
            role = (m.get("role") or "").lower()
            if role in {"platform", "platform_entry_only", "platform_exit_only",
                        "stop", "stop_entry_only", "stop_exit_only", "station"}:
                continue
            wid = m.get("ref")
            if isinstance(wid, int):
                if wid in seen:
                    continue
                seen.add(wid)
            geom = m.get("geometry") or []
            seq: list[tuple[float, float]] = []
            for pt in geom:
                lat = pt.get("lat")
                lon = pt.get("lon")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    seq.append((float(lat), float(lon)))
            if len(seq) >= 2:
                ways.append(seq)
    return ways


def _stitch(ways: list[list[tuple[float, float]]]) -> list[list[float]]:
    """Greedy nearest-endpoint stitch of disjoint ways into one polyline.

    OSM rail relations don't guarantee that member ways are ordered
    end-to-end (especially after we de-duplicate across sub-relations), so
    naive concatenation produces visible "leaps" between disjoint segments.

    Algorithm:
      1. Start with the way whose first endpoint has the southernmost
         latitude (so the polyline runs roughly south→north for HK lines).
      2. Repeatedly pick the unvisited way whose nearer endpoint is closest
         to the current tail; reverse it if needed; append, dropping the
         duplicate joining point when within ~1 m.
      3. If the nearest unvisited endpoint is farther than ~250 m we give
         up — the remaining ways are isolated branches/sidings we don't
         want jumping into the polyline.
    """
    if not ways:
        return []

    # Tunable: ~0.03 deg ≈ 3.3 km. Wide enough to bridge cross-harbour
    # tunnels (where OSM may model the under-water track as a separate way
    # disconnected from station platforms — e.g. AEL/TCL Kowloon→HK Island
    # is ~2 km), narrow enough that we won't snap onto unrelated lines.
    JOIN_THRESHOLD_SQ = 0.03 ** 2

    remaining = [list(w) for w in ways if len(w) >= 2]
    # Pick the way with the southernmost endpoint as our seed.
    seed_idx = min(
        range(len(remaining)),
        key=lambda i: min(remaining[i][0][0], remaining[i][-1][0]),
    )
    seed = remaining.pop(seed_idx)
    # Orient seed so its first point is the southern one.
    if seed[0][0] > seed[-1][0]:
        seed = list(reversed(seed))
    out: list[list[float]] = [[float(p[0]), float(p[1])] for p in seed]

    while remaining:
        tail = out[-1]
        best_i = -1
        best_d = float("inf")
        best_reversed = False
        for i, w in enumerate(remaining):
            d_first = (w[0][0] - tail[0]) ** 2 + (w[0][1] - tail[1]) ** 2
            d_last = (w[-1][0] - tail[0]) ** 2 + (w[-1][1] - tail[1]) ** 2
            if d_first < best_d:
                best_d, best_i, best_reversed = d_first, i, False
            if d_last < best_d:
                best_d, best_i, best_reversed = d_last, i, True
        if best_d > JOIN_THRESHOLD_SQ:
            break
        w = remaining.pop(best_i)
        if best_reversed:
            w = list(reversed(w))
        # Drop the duplicate joining point if effectively the same (~1 m).
        start = 1 if (abs(w[0][0] - tail[0]) < 1e-5
                      and abs(w[0][1] - tail[1]) < 1e-5) else 0
        out.extend([float(p[0]), float(p[1])] for p in w[start:])
    return out


def build_line(line_id: str, queries: list[str]) -> list[list[float]]:
    """Return the stitched polyline for ``line_id`` or [] if not found."""
    for q in queries:
        result = _overpass(q)
        elements = result.get("elements") or []
        if not elements:
            time.sleep(THROTTLE_SECONDS)
            continue
        ways = _extract_ways(elements)
        if ways:
            stitched = _stitch(ways)
            time.sleep(THROTTLE_SECONDS)
            return stitched
        time.sleep(THROTTLE_SECONDS)
    return []


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Building MTR rail geometry → {OUT_DIR}")
    summary: list[tuple[str, int]] = []
    for line_id, queries in LINE_QUERIES.items():
        print(f"[{line_id}] querying Overpass…")
        coords = build_line(line_id, queries)
        if not coords:
            print(f"  [{line_id}] no geometry returned; skipping.",
                  file=sys.stderr)
            summary.append((line_id, 0))
            continue
        out_path = OUT_DIR / f"{line_id}.json"
        out_path.write_text(
            json.dumps(
                {"coords": coords, "source": "osm-overpass"},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        print(f"  [{line_id}] wrote {len(coords)} points → {out_path}")
        summary.append((line_id, len(coords)))

    print()
    print("Summary:")
    for line_id, n in summary:
        status = "ok" if n >= 10 else "FALLBACK"
        print(f"  {line_id}: {n} points  [{status}]")
    ok = sum(1 for _, n in summary if n >= 10)
    print(f"\n{ok}/{len(summary)} lines have real OSM track geometry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
