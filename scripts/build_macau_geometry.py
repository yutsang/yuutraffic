"""Build road-following polylines for Macau bus and shuttle routes.

For each route in ``data/01_raw/macau_bus.json`` and
``data/01_raw/macau_shuttles.json`` we resolve the ordered ``(lat, lng)`` stop
sequence and ask OSRM (driving profile) for a road-following geometry.  Long
sequences are chunked into batches of 8 waypoints (mirroring the HK pipeline)
and concatenated.  Results are written one file per route at::

    data/02_intermediate/macau_route_geometry/{rk}_1.json

A SHA-1 cache keyed by the stop sequence lives at
``data/02_intermediate/macau_route_geometry_cache.json`` so reruns skip routes
whose stops haven't changed.

OSRM is called directly with ``urllib.request`` (no dependency on the HK
``yuutraffic.web`` pipeline beyond an optional fast path) so this stays
self-contained and can be run as a standalone script.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_macau_geometry")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "01_raw"
INT = ROOT / "data" / "02_intermediate"

MACAU_BUS = RAW / "macau_bus.json"
MACAU_SHUTTLES = RAW / "macau_shuttles.json"

OUT_DIR = INT / "macau_route_geometry"
CACHE_PATH = INT / "macau_route_geometry_cache.json"

OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
USER_AGENT = "YuuTraffic/1.0"
THROTTLE_SEC = 1.1
TIMEOUT_SEC = 30
BATCH = 8  # max waypoints per OSRM call (matches HK pipeline)
PROGRESS_EVERY = 20


def _seq_hash(coords: list[tuple[float, float]]) -> str:
    """Stable SHA-1 of an ordered (lat, lng) sequence (rounded to 5 dp)."""
    rounded = [(round(la, 5), round(lg, 5)) for la, lg in coords]
    payload = json.dumps(rounded, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _osrm_call(seg: list[tuple[float, float]]) -> list[list[float]] | None:
    """Call OSRM for a single segment (<= BATCH waypoints).

    Returns a list of [lat, lng] points or ``None`` if the call fails
    (non-200, timeout, malformed body, etc.).
    """
    coords_str = ";".join(f"{lg},{la}" for la, lg in seg)
    url = f"{OSRM_URL}/{coords_str}?overview=full&geometries=geojson"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            if resp.status != 200:
                logger.warning("OSRM HTTP %s for %d-point segment", resp.status, len(seg))
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.warning("OSRM HTTPError %s for %d-point segment", e.code, len(seg))
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("OSRM network error (%s) for %d-point segment", e, len(seg))
        return None
    except json.JSONDecodeError as e:
        logger.warning("OSRM bad JSON (%s) for %d-point segment", e, len(seg))
        return None

    if data.get("code") != "Ok" or not data.get("routes"):
        logger.warning("OSRM code=%s for %d-point segment", data.get("code"), len(seg))
        return None
    geom = data["routes"][0].get("geometry") or {}
    coords = geom.get("coordinates") or []
    if not coords:
        return None
    return [[c[1], c[0]] for c in coords]  # GeoJSON is [lng, lat]


def build_route_geometry(coords: list[tuple[float, float]]) -> list[list[float]] | None:
    """Build a road-following polyline for an ordered stop list.

    Chunks into batches of ``BATCH`` waypoints, sleeping ``THROTTLE_SEC``
    between calls.  Returns the concatenated polyline, or ``None`` if any
    chunk fails (caller falls back to straight lines).
    """
    if len(coords) < 2:
        return None
    if len(coords) <= BATCH:
        return _osrm_call(coords)

    out: list[list[float]] = []
    i = 0
    first = True
    while i < len(coords) - 1:
        end = min(i + BATCH, len(coords))
        seg = coords[i:end]
        chunk = _osrm_call(seg)
        if chunk is None:
            return None
        if first:
            out.extend(chunk)
            first = False
        else:
            # Drop the duplicated joining point.
            out.extend(chunk[1:] if chunk else [])
        i = end - 1
        if i < len(coords) - 1:
            time.sleep(THROTTLE_SEC)
    return out


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Cache file unreadable; starting fresh")
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, separators=(",", ":")), encoding="utf-8"
    )


def _write_geom(rk: str, coords: list[list[float]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{rk}_1.json"
    path.write_text(
        json.dumps({"coords": coords}, separators=(",", ":")),
        encoding="utf-8",
    )


def _resolve_stops(seq: list[str], stops: dict[str, dict]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for sid in seq:
        s = stops.get(sid)
        if not s:
            continue
        out.append((float(s["la"]), float(s["lg"])))
    return out


def _process(
    rk: str,
    coords: list[tuple[float, float]],
    cache: dict,
    stats: dict,
    is_last: bool,
) -> None:
    if len(coords) < 2:
        stats["skipped_too_short"] += 1
        return

    h = _seq_hash(coords)
    out_path = OUT_DIR / f"{rk}_1.json"
    if cache.get(rk) == h and out_path.exists():
        stats["cached"] += 1
        return

    geom = build_route_geometry(coords)
    if not geom:
        stats["failed"] += 1
        logger.warning("OSRM failed for %s; falling back to straight line in export", rk)
        return

    _write_geom(rk, geom)
    cache[rk] = h
    stats["built"] += 1

    if not is_last:
        time.sleep(THROTTLE_SEC)


def main() -> int:
    if not MACAU_BUS.exists():
        logger.error("Missing %s", MACAU_BUS)
        return 1
    if not MACAU_SHUTTLES.exists():
        logger.error("Missing %s", MACAU_SHUTTLES)
        return 1

    bus_raw = json.loads(MACAU_BUS.read_text(encoding="utf-8"))
    sc_raw = json.loads(MACAU_SHUTTLES.read_text(encoding="utf-8"))

    bus_stops = bus_raw.get("stops", {})
    bus_routes = bus_raw.get("routes", [])
    sc_stops = sc_raw.get("stops", {})
    sc_routes = sc_raw.get("routes", [])

    cache = _load_cache()
    stats = {"built": 0, "cached": 0, "failed": 0, "skipped_too_short": 0}

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- DSAT bus routes ---
    bus_total = len(bus_routes)
    logger.info("Processing %d Macau bus routes", bus_total)
    for idx, r in enumerate(bus_routes, start=1):
        rid = r.get("id")
        if not rid:
            continue
        rk = f"MOB_{rid}"
        seq = r.get("stops_outbound", []) or []
        coords = _resolve_stops(seq, bus_stops)
        is_last = idx == bus_total and not sc_routes
        _process(rk, coords, cache, stats, is_last)
        if idx % PROGRESS_EVERY == 0 or idx == bus_total:
            logger.info(
                "  bus %d/%d (built=%d cached=%d failed=%d)",
                idx, bus_total,
                stats["built"], stats["cached"], stats["failed"],
            )
            _save_cache(cache)

    # --- Casino shuttles ---
    sc_total = len(sc_routes)
    logger.info("Processing %d Macau casino shuttle routes", sc_total)
    for idx, r in enumerate(sc_routes, start=1):
        rid = r.get("id")
        if not rid:
            continue
        rk = f"MOSC_{rid}"
        from_code = r.get("from")
        to_code = r.get("to")
        if not from_code or not to_code:
            continue
        from_s = sc_stops.get(from_code)
        to_s = sc_stops.get(to_code)
        if not from_s or not to_s:
            continue
        coords = [
            (float(from_s["la"]), float(from_s["lg"])),
            (float(to_s["la"]), float(to_s["lg"])),
        ]
        is_last = idx == sc_total
        _process(rk, coords, cache, stats, is_last)
        if idx % PROGRESS_EVERY == 0 or idx == sc_total:
            logger.info(
                "  shuttle %d/%d (built=%d cached=%d failed=%d)",
                idx, sc_total,
                stats["built"], stats["cached"], stats["failed"],
            )
            _save_cache(cache)

    _save_cache(cache)
    logger.info(
        "Done. built=%d cached=%d failed=%d skipped_too_short=%d",
        stats["built"], stats["cached"], stats["failed"], stats["skipped_too_short"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
