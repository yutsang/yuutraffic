"""
Precompute OSM route geometry for all routes. Run before starting Streamlit for fast map loading.
Usage: yuutraffic precompute  or  python -m yuutraffic precompute

智能檢測: If stops unchanged, skip recalculation (uses stop sequence hash).
Segment cache: Same inter-stops = reuse routing (no duplicate API calls).
Uses ThreadPoolExecutor for parallel OSRM requests.
"""

import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from .config import load_config
from .web import get_osm_route_with_waypoints, load_all_route_stops

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _stops_hash(dir_stops) -> str:
    """Hash of stop sequence for 智能 detection - same stops = skip recalc."""
    ids = dir_stops["stop_id"].astype(str).tolist()
    seq = dir_stops["sequence"].astype(int).tolist()
    data = ",".join(f"{s}:{i}" for s, i in zip(ids, seq))
    return hashlib.sha256(data.encode()).hexdigest()[:16]


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
    """Worker: (key, coords, h, segment_cache, segment_lock, on_api_call) -> (key, geom, h)."""
    key, coords, h, segment_cache, segment_lock, on_api_call = args
    try:
        geom = get_osm_route_with_waypoints(
            coords,
            segment_cache=segment_cache,
            segment_lock=segment_lock,
            on_api_call=on_api_call,
        )
        return (key, geom, h)
    except Exception:
        return (key, None, h)


def run_precompute(limit: int | None = None, workers: int = 8) -> int:
    """Precompute OSM routing for all route directions. Returns count of routes cached.
    智能 detection: skip if stops unchanged (hash match).
    Uses multithreading (workers) for parallel OSRM requests.
    If limit is set, only process that many routes (for testing)."""
    cache = load_geometry_cache()
    all_stops = load_all_route_stops()
    if not all_stops:
        logger.error("No route stops in database")
        return 0
    tasks = []
    migrated = 0
    skipped_same = 0
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
            h = _stops_hash(dir_stops)
            entry = cache.get(key)
            if isinstance(entry, dict) and entry.get("hash") == h:
                skipped_same += 1
                continue
            if isinstance(entry, list):
                cache[key] = {"hash": h, "coords": entry}
                migrated += 1
                continue
            tasks.append((key, coords, h))
    if limit:
        tasks = tasks[:limit]

    if not tasks:
        if migrated > 0:
            save_geometry_cache(cache)
        logger.info("Nothing to compute. Total cached: %d", len(cache))
        return len(cache)

    total_api_calls = sum(_n_api_calls(c) for _, c, _ in tasks)
    segment_cache = {}
    segment_lock = threading.Lock()
    pbar_lock = threading.Lock()
    routes_done = [0]
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
            (k, c, h, segment_cache, segment_lock, on_api_call) for k, c, h in tasks
        ]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_fetch_route_geom, t): t for t in task_args}
            for future in as_completed(futures):
                key, geom, h = future.result()
                if geom:
                    cache[key] = {"hash": h, "coords": geom}
                    total += 1
                with pbar_lock:
                    routes_done[0] += 1
                    pbar.update(1)
                    pbar.set_postfix_str(f"API {api_done[0]}/{total_api_calls}")
    if total > 0 or migrated > 0:
        save_geometry_cache(cache)
    logger.info(
        "Precomputed %d new. Total: %d routes. API calls: %d made (est. %d max, saved %d via segment cache)",
        total,
        len(cache),
        api_done[0],
        total_api_calls,
        max(0, total_api_calls - api_done[0]),
    )
    return len(cache)


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
