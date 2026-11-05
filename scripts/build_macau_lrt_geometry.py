#!/usr/bin/env python3
"""Build per-line Macau LRT (MLM) track geometry from OpenStreetMap via Overpass.

The static export pipeline (``scripts/export_static.py``) chains LRT station
coordinates with ``L.polyline`` for each Macau LRT line, producing visibly
straight segments that don't follow the actual rail alignment. This script
mirrors ``scripts/build_mtr_rail_geometry.py`` for HK MTR — it queries OSM
for ``route=light_rail`` relations tagged Macau/MLM, matches them to one of
the four line ids (TPL, BAR, HQX, SPV), then concatenates each relation's
member ways into a single polyline.

Output:
    data/02_intermediate/macau_lrt_geometry/{line_id}.json
        {"coords": [[lat, lng], ...], "source": "osm-overpass"}

Run once per geometry refresh (script is idempotent). Failures are tolerated
— ``export_static.py`` falls back to the straight-line connector for any
line whose JSON is missing or has fewer than 10 points. Recent extensions
(HQX = Hengqin, SPV = Seac Pai Van) may not yet be fully mapped in OSM, so
a fallback there is expected.
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
OUT_DIR = ROOT / "data" / "02_intermediate" / "macau_lrt_geometry"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "YuuTraffic/1.0"

# Overpass nominally allows 1 query per ~2 s burst on the public endpoint.
THROTTLE_SECONDS = 2.0

# Single bulk query — pulls every ``route=light_rail`` relation in the Macau
# area in one shot, then we match each to one of the four MLM line ids in
# Python. Avoids needing one HTTP round-trip per line.
BULK_QUERY = (
    'relation["route"="light_rail"]["network"~"Macau|MLM|澳門",i];'
)

# Per-line keyword sets used to match a returned relation to a line id. We
# check name / name:en / name:zh / ref tags case-insensitively. The first
# matching entry wins, so list more specific phrases first.
#
# Note: as of 2026-05 OSM does not have a standalone "Barra Line" relation —
# the new BAR extension (TFT ↔ Barra, opened Dec 2024) is folded into the
# Taipa Line relation, which now runs all the way to 媽閣. We therefore
# don't list BAR keywords here; the Taipa Line relation supplies geometry
# for both TPL and BAR (the latter via slicing — see ``_derive_barra``).
LINE_KEYWORDS: dict[str, list[str]] = {
    "TPL": ["taipa line", "linha da taipa", "氹仔線"],
    "HQX": ["hengqin", "linha de hengqin", "橫琴線", "橫琴延伸線"],
    "SPV": ["seac pai van", "linha de seac pai van", "石排灣線", "石排灣支線"],
}

# Reference station coordinates for slicing the BAR sub-segment out of the
# combined Taipa-Line OSM polyline. From data/01_raw/macau_lrt.json.
BAR_TFT = (22.15514, 113.57881)   # 氹仔碼頭 Taipa Ferry Terminal
BAR_BAR = (22.18723, 113.53055)   # 媽閣 Barra


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


def _relation_text_blob(rel: dict) -> str:
    """Concatenate a relation's identifying tags into one lowercase string
    so keyword matching can search them all at once."""
    tags = rel.get("tags", {}) or {}
    parts = [
        tags.get("name", ""),
        tags.get("name:en", ""),
        tags.get("name:zh", ""),
        tags.get("name:zh-Hant", ""),
        tags.get("name:pt", ""),
        tags.get("ref", ""),
        tags.get("from", ""),
        tags.get("to", ""),
        tags.get("description", ""),
    ]
    return " | ".join(p for p in parts if p).lower()


def _relation_station_blob(rel: dict) -> str:
    """Collect station-member names so we can fuzzy-match by endpoints when
    the relation's own name tags are uninformative."""
    chunks: list[str] = []
    for m in rel.get("members", []) or []:
        role = (m.get("role") or "").lower()
        if "stop" not in role and "station" not in role and "platform" not in role:
            continue
        # Overpass embeds a member's tags only when ``out geom;`` returns
        # them — typically yes for nodes. Be defensive.
        for k in ("name", "name:en", "name:zh", "name:zh-Hant"):
            v = (m.get("tags") or {}).get(k)
            if v:
                chunks.append(v)
    return " ".join(chunks).lower()


def _classify_relation(rel: dict) -> str | None:
    """Return the line_id this relation belongs to, or None if it doesn't
    match any of the MLM lines we care about (TPL/HQX/SPV — BAR derives
    from TPL by slicing)."""
    blob = _relation_text_blob(rel)
    for line_id, kws in LINE_KEYWORDS.items():
        if any(kw in blob for kw in kws):
            return line_id
    return None


def _derive_barra(taipa_coords: list[list[float]]) -> list[list[float]]:
    """OSM models the post-2024 Taipa-to-Barra alignment as a single
    "Taipa Line" relation, so we slice the BAR sub-segment out of TPL's
    polyline by finding the indices closest to TFT and BAR station
    coordinates and returning everything in between (oriented TFT → BAR).
    """
    if not taipa_coords:
        return []

    def closest_index(target: tuple[float, float]) -> int:
        return min(
            range(len(taipa_coords)),
            key=lambda i: (
                (taipa_coords[i][0] - target[0]) ** 2
                + (taipa_coords[i][1] - target[1]) ** 2
            ),
        )

    i_tft = closest_index(BAR_TFT)
    i_bar = closest_index(BAR_BAR)
    if i_tft == i_bar:
        return []
    if i_tft < i_bar:
        seg = taipa_coords[i_tft:i_bar + 1]
    else:
        seg = list(reversed(taipa_coords[i_bar:i_tft + 1]))
    return [list(p) for p in seg]


def _extract_ways(relations: list[dict]) -> list[list[tuple[float, float]]]:
    """Return a list of unique way coordinate sequences across all input
    relations. De-dupes by way id so two parallel direction sub-relations
    don't double the geometry."""
    seen: set[int] = set()
    ways: list[list[tuple[float, float]]] = []
    for rel in relations:
        for m in rel.get("members", []) or []:
            if m.get("type") != "way":
                continue
            role = (m.get("role") or "").lower()
            if role in {
                "platform", "platform_entry_only", "platform_exit_only",
                "stop", "stop_entry_only", "stop_exit_only", "station",
            }:
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

    Same algorithm as ``build_mtr_rail_geometry._stitch`` but with a
    relaxed join threshold — Macau LRT viaducts cross water (e.g. the
    Sai Van bridge between Taipa and the peninsula on BAR/the future
    extensions) so OSM may model the over-water track as a separate way
    disconnected from station platforms.
    """
    if not ways:
        return []

    # ~0.02 deg ≈ 2.2 km. Wide enough for the Sai Van bridge, narrow enough
    # to avoid snapping onto the (entirely unrelated) HK Light Rail in
    # Yuen Long ~70 km away.
    JOIN_THRESHOLD_SQ = 0.02 ** 2

    remaining = [list(w) for w in ways if len(w) >= 2]
    seed_idx = min(
        range(len(remaining)),
        key=lambda i: min(remaining[i][0][0], remaining[i][-1][0]),
    )
    seed = remaining.pop(seed_idx)
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
        start = 1 if (abs(w[0][0] - tail[0]) < 1e-5
                      and abs(w[0][1] - tail[1]) < 1e-5) else 0
        out.extend([float(p[0]), float(p[1])] for p in w[start:])
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Building Macau LRT geometry → {OUT_DIR}")

    print("Querying Overpass for Macau light_rail relations…")
    result = _overpass(BULK_QUERY)
    time.sleep(THROTTLE_SECONDS)
    elements = result.get("elements") or []
    relations = [e for e in elements if e.get("type") == "relation"]
    print(f"  Overpass returned {len(relations)} relation(s).")

    grouped: dict[str, list[dict]] = {"TPL": [], "HQX": [], "SPV": []}
    unmatched = 0
    for rel in relations:
        line_id = _classify_relation(rel)
        if line_id is None:
            unmatched += 1
            continue
        grouped[line_id].append(rel)
    if unmatched:
        print(f"  ({unmatched} relation(s) didn't match any MLM line — ignored.)")

    # Build directly-matched lines first.
    built_coords: dict[str, list[list[float]]] = {}
    for line_id in ("TPL", "HQX", "SPV"):
        rels = grouped[line_id]
        if not rels:
            print(
                f"  WARN [{line_id}]: no OSM relation matched; "
                f"export will fall back to straight lines.",
                file=sys.stderr,
            )
            built_coords[line_id] = []
            continue
        ways = _extract_ways(rels)
        coords = _stitch(ways) if ways else []
        if not coords:
            print(
                f"  WARN [{line_id}]: relation matched but yielded no usable "
                f"way geometry; will fall back to straight lines.",
                file=sys.stderr,
            )
        built_coords[line_id] = coords

    # Derive BAR from TPL: OSM has no separate Barra Line relation as of
    # 2026-05; the post-2024 extension is part of the Taipa-Line relation.
    bar_coords = _derive_barra(built_coords.get("TPL", []))
    if not bar_coords:
        print(
            "  WARN [BAR]: could not derive BAR sub-segment from TPL; "
            "export will fall back to straight lines.",
            file=sys.stderr,
        )
    built_coords["BAR"] = bar_coords

    summary: list[tuple[str, int]] = []
    for line_id in ("TPL", "BAR", "HQX", "SPV"):
        coords = built_coords.get(line_id, [])
        if not coords:
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
