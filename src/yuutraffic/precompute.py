"""
Precompute OSM route geometry for all routes. Run before starting Streamlit for fast map loading.
Usually invoked via `yuutraffic --update`. Direct: python -m yuutraffic.precompute

智能檢測: If stops unchanged, skip recalculation (uses stop sequence hash).
Segment cache: Same inter-stops = reuse routing (no duplicate API calls).
Uses ThreadPoolExecutor for parallel OSRM requests.

Storage: data/02_intermediate/route_geometry/{route_key}_{direction}.json
Each file includes: stop name, stop_id (API), company, OSM node sequence, coords.
Editable per-route for manual adjustment.
"""

import hashlib
import json
import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from .config import load_config
from .database_manager import KMBDatabaseManager
from .web import get_osm_route_with_waypoints, load_all_route_stops

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _stops_hash(dir_stops) -> str:
    """Hash of stop sequence for 智能 detection - same stops = skip recalc."""
    ids = dir_stops["stop_id"].astype(str).tolist()
    seq = dir_stops["sequence"].astype(int).tolist()
    data = ",".join(f"{s}:{i}" for s, i in zip(ids, seq))
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def get_geometry_dir() -> Path | None:
    """Path to per-route geometry dir. None if not configured."""
    params = load_config()
    d = params.get("route_geometry_dir")
    return Path(d) if d else None


def _manifest_path() -> Path | None:
    d = get_geometry_dir()
    return (d / "manifest.json") if d else None


def load_manifest() -> dict[str, str]:
    """Load {key: hash} for fast skip detection."""
    p = _manifest_path()
    if not p or not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Could not load manifest: %s", e)
        return {}


def save_manifest(manifest: dict[str, str]) -> None:
    p = _manifest_path()
    if not p:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(manifest, f, separators=(",", ":"))


def _closest_point_index(lat: float, lng: float, coords: list[list[float]]) -> int:
    """Index in coords closest to (lat, lng)."""
    best_i, best_d = 0, float("inf")
    for i, c in enumerate(coords):
        d = (c[0] - lat) ** 2 + (c[1] - lng) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def _compute_stops_with_osm_sequences(
    dir_stops, coords: list[list[float]]
) -> list[dict]:
    """Build stops list with osm_node_sequence (index in OSM polyline)."""
    stops = []
    for _, s in dir_stops.iterrows():
        lat, lng = s.get("lat"), s.get("lng")
        try:
            lat_f, lng_f = float(lat), float(lng)
        except (TypeError, ValueError):
            continue
        if math.isnan(lat_f) or math.isnan(lng_f):
            continue
        idx = _closest_point_index(lat_f, lng_f, coords)
        stops.append(
            {
                "stop_id": str(s.get("stop_id", "")),
                "stop_name": str(s.get("stop_name", "") or ""),
                "stop_name_tc": str(s.get("stop_name_tc", "") or ""),
                "sequence": int(s.get("sequence", 0)),
                "company": str(s.get("company", "") or ""),
                "lat": lat_f,
                "lng": lng_f,
                "osm_node_sequence": idx,
                "osm_node_name": str(s.get("stop_name", "") or ""),
            }
        )
    return stops


def _route_file_path(key: str) -> Path | None:
    d = get_geometry_dir()
    return (d / f"{key}.json") if d else None


def load_route_entry(key: str) -> dict | None:
    """Load a single route from dir storage. Returns None if not found."""
    p = _route_file_path(key)
    if not p or not p.exists():
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        logger.debug("Could not load route %s: %s", key, e)
        return None


def save_route_entry(key: str, entry: dict) -> None:
    """Save a single route to dir storage (pretty JSON for manual edits)."""
    p = _route_file_path(key)
    if not p:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)


def get_cache_path() -> Path:
    params = load_config()
    cache = params.get(
        "route_geometry_cache", "data/02_intermediate/route_geometry_cache.json"
    )
    return Path(cache)


def load_geometry_cache() -> dict:
    """Load precomputed route geometry from JSON cache."""
    path = get_cache_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Could not load geometry cache: %s", e)
        return {}


def save_geometry_cache(cache: dict) -> None:
    path = get_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f, separators=(",", ":"))
    logger.info("Saved geometry cache to %s (%d routes)", path, len(cache))


def _n_api_calls(coords: list, batch: int = 8) -> int:
    """Number of OSRM API calls needed for this route."""
    if len(coords) <= batch:
        return 1
    n = 0
    i = 0
    while i < len(coords) - 1:
        end = min(i + batch, len(coords))
        n += 1
        i = end - 1
    return n


def _fetch_route_geom(args: tuple) -> tuple:
    """Worker: (key, coords, h, dir_stops, route_id, rk, company, segment_cache, segment_lock, on_api_call)
    -> (key, geom, h, dir_stops, route_id, rk, company)."""
    (
        key,
        coords,
        h,
        dir_stops,
        route_id,
        rk,
        company,
        segment_cache,
        segment_lock,
        on_api_call,
    ) = args
    try:
        geom = get_osm_route_with_waypoints(
            coords,
            segment_cache=segment_cache,
            segment_lock=segment_lock,
            on_api_call=on_api_call,
        )
        return (key, geom, h, dir_stops, route_id, rk, company)
    except Exception:
        return (key, None, h, dir_stops, route_id, rk, company)


def _migrate_legacy_cache_to_dir() -> int:
    """Migrate old single-file cache to per-route dir. Returns count migrated."""
    geom_dir = get_geometry_dir()
    if not geom_dir:
        return 0
    geom_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    if manifest:
        return 0  # Already using dir
    cache = load_geometry_cache()
    if not cache:
        return 0
    all_stops = load_all_route_stops()
    if not all_stops:
        return 0
    migrated = 0
    for key, entry in cache.items():
        if key in manifest:
            continue
        if isinstance(entry, list):
            coords = entry
            h = ""
            for rid, df in all_stops.items():
                for direction in df["direction"].unique():
                    if f"{rid}_{int(direction)}" == key:
                        dir_stops = df[df["direction"] == direction].sort_values(
                            "sequence"
                        )
                        h = _stops_hash(dir_stops)
                        company = (
                            dir_stops["company"].iloc[0]
                            if "company" in dir_stops.columns
                            else ""
                        ) or ""
                        stops = _compute_stops_with_osm_sequences(dir_stops, coords)
                        save_route_entry(
                            key,
                            {
                                "hash": h,
                                "route_id": rid,
                                "route_key": rid,
                                "direction": int(direction),
                                "company": str(company),
                                "stops": stops,
                                "coords": coords,
                            },
                        )
                        manifest[key] = h
                        migrated += 1
                        break
                else:
                    continue
                break
        elif isinstance(entry, dict) and entry.get("coords"):
            coords = entry["coords"]
            h = entry.get("hash", "")
            for rid, df in all_stops.items():
                for direction in df["direction"].unique():
                    if f"{rid}_{int(direction)}" == key:
                        dir_stops = df[df["direction"] == direction].sort_values(
                            "sequence"
                        )
                        if not h:
                            h = _stops_hash(dir_stops)
                        company = (
                            dir_stops["company"].iloc[0]
                            if "company" in dir_stops.columns
                            else ""
                        ) or ""
                        stops = _compute_stops_with_osm_sequences(dir_stops, coords)
                        save_route_entry(
                            key,
                            {
                                "hash": h,
                                "route_id": rid,
                                "route_key": rid,
                                "direction": int(direction),
                                "company": str(company),
                                "stops": stops,
                                "coords": coords,
                            },
                        )
                        manifest[key] = h
                        migrated += 1
                        break
                else:
                    continue
                break
    if migrated > 0:
        save_manifest(manifest)
        logger.info("Migrated %d routes from legacy cache to %s", migrated, geom_dir)
    return migrated


def run_precompute(limit: int | None = None, workers: int = 8) -> int:
    """Precompute OSM routing for all route directions. Returns count of routes cached.
    Always incremental: skips routes if stops sequence hash matches the database or manifest.
    Uses multithreading (workers) for parallel OSRM requests.
    Saves to data/02_intermediate/route_geometry/ (per-route JSON, editable).
    If limit is set, only process that many routes (for testing)."""
    geom_dir = get_geometry_dir()
    use_dir = geom_dir is not None
    if use_dir:
        _migrate_legacy_cache_to_dir()
        manifest = load_manifest()
        cache = {}  # Not used in dir mode
    else:
        cache = load_geometry_cache()
        manifest = {}

    all_stops = load_all_route_stops()
    if not all_stops:
        logger.error("No route stops in database")
        return 0

    params = load_config()
    db_manager = KMBDatabaseManager(params["database"]["path"], init_db=False)

    # Get current DB status for all route directions
    db_hashes = db_manager.get_route_geometry_hashes()

    tasks = []
    skipped_same = 0

    # First, collect all current hashes for detection
    current_hashes = {}
    for route_id, df in all_stops.items():
        for direction in df["direction"].unique():
            dir_stops = df[df["direction"] == direction].sort_values("sequence")
            key = f"{route_id}_{int(direction)}"
            current_hashes[key] = _stops_hash(dir_stops)

    for route_id, df in all_stops.items():
        for direction in df["direction"].unique():
            dir_stops = df[df["direction"] == direction].sort_values("sequence")
            coords = [
                (s["lat"], s["lng"])
                for _, s in dir_stops.iterrows()
                if s.get("lat") is not None and s.get("lng") is not None
            ]
            if len(coords) < 2:
                continue

            key = f"{route_id}_{int(direction)}"
            h = current_hashes[key]
            company = (
                dir_stops["company"].iloc[0] if "company" in dir_stops.columns else ""
            ) or ""

            # Use route_key (KMB_65X) if available from DB to match DB hashes
            rk = (
                dir_stops["route_key"].iloc[0]
                if not dir_stops.empty and "route_key" in dir_stops.columns
                else route_id
            )

            # Incremental check: Skip if hash matches either DB or manifest
            if db_hashes.get((str(rk), int(direction))) == h:
                skipped_same += 1
                continue

            if use_dir and manifest.get(key) == h:
                # Sync DB if manifest is ahead
                db_manager.update_route_geometry_status(rk, int(direction), h)
                skipped_same += 1
                continue

            if not use_dir:
                entry = cache.get(key)
                if isinstance(entry, dict) and entry.get("hash") == h:
                    db_manager.update_route_geometry_status(rk, int(direction), h)
                    skipped_same += 1
                    continue

            tasks.append((key, coords, h, dir_stops, route_id, rk, company))

    if limit:
        tasks = tasks[:limit]

    if not tasks:
        if use_dir:
            logger.info("Nothing to compute. Total cached: %d", len(manifest))
            return len(manifest)
        logger.info("Nothing to compute. Total cached: %d", len(cache))
        return len(cache)

    total_api_calls = sum(_n_api_calls(c) for _, c, *_ in tasks)
    segment_cache = {}
    segment_lock = threading.Lock()
    manifest_lock = threading.Lock()
    pbar_lock = threading.Lock()
    api_done = [0]

    logger.info(
        "智能檢測: skipped %d (stops unchanged). Computing %d routes, ~%d API calls (workers=%d).",
        skipped_same,
        len(tasks),
        total_api_calls,
        workers,
    )
    total = 0
    with tqdm(total=len(tasks), desc="Routes", unit="route") as pbar:

        def on_api_call():
            with pbar_lock:
                api_done[0] += 1
                pbar.set_postfix_str(f"API {api_done[0]}/{total_api_calls}")

        task_args = [
            (k, c, h, ds, rid, rk, co, segment_cache, segment_lock, on_api_call)
            for k, c, h, ds, rid, rk, co in tasks
        ]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_fetch_route_geom, t): t for t in task_args}
            for future in as_completed(futures):
                key, geom, h, dir_stops, route_id, rk, company = future.result()
                if geom:
                    if use_dir:
                        stops = _compute_stops_with_osm_sequences(dir_stops, geom)
                        entry = {
                            "hash": h,
                            "route_id": route_id,
                            "route_key": rk,
                            "direction": (
                                int(dir_stops["direction"].iloc[0])
                                if not dir_stops.empty
                                else 0
                            ),
                            "company": company,
                            "stops": stops,
                            "coords": geom,
                        }
                        save_route_entry(key, entry)
                        db_manager.update_route_geometry_status(
                            rk, int(entry["direction"]), h
                        )
                        with manifest_lock:
                            manifest[key] = h
                            save_manifest(manifest)
                    else:
                        cache[key] = {"hash": h, "coords": geom}
                    total += 1
                with pbar_lock:
                    pbar.update(1)
                    pbar.set_postfix_str(f"API {api_done[0]}/{total_api_calls}")
    if not use_dir and total > 0:
        save_geometry_cache(cache)
    final_count = len(manifest) if use_dir else len(cache)
    logger.info(
        "Precomputed %d new. Total: %d routes. API calls: %d made (est. %d max, saved %d via segment cache)",
        total,
        final_count,
        api_done[0],
        total_api_calls,
        max(0, total_api_calls - api_done[0]),
    )
    return final_count


def main():
    import argparse
    import os
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    default_workers = max(1, int((os.cpu_count() or 8) * 0.8))
    parser = argparse.ArgumentParser(
        description="Precompute OSM route geometry for fast map loading"
    )
    parser.add_argument(
        "--limit", type=int, help="Limit number of routes (for testing)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=default_workers,
        help=f"Parallel workers (default: 80%% of CPU = {default_workers})",
    )
    args = parser.parse_args()
    run_precompute(limit=args.limit, workers=args.workers)


if __name__ == "__main__":
    main()
