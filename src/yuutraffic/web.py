"""
Web app logic: data loading, route mapping, search.
"""

import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import folium
import pandas as pd
import requests
import streamlit as st
from folium.plugins import LocateControl

from .config import load_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

params = load_config()

# Config constants
HK_CENTER = [params["map"]["center"]["lat"], params["map"]["center"]["lng"]]
DEFAULT_ZOOM = params["map"]["default_zoom"]
ROUTE_ZOOM = params["map"]["auto_zoom"]["route_zoom"]
STOP_ZOOM = params["map"]["auto_zoom"]["stop_zoom"]
DB_PATH = params["database"]["path"]
OSM_BASE_URL = params["api"]["osm_routing_url"]
MAX_WAYPOINTS = params["osm"].get("max_waypoints", 15)
OSM_TIMEOUT = params["osm"].get("timeout", 30)

MIN_STOPS_FOR_ROUTE = 2
HTTP_OK = 200
ZOOM_VERY_SPREAD = 0.3
ZOOM_MODERATE_SPREAD = 0.2
ZOOM_SOME_SPREAD = 0.1
ZOOM_CLOSE = 0.05
ZOOM_VERY_CLOSE = 0.02


def _ensure_schema_columns():
    """Add origin_tc, destination_tc, stop_name_tc columns if missing (migration for existing DBs)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(routes)")
            route_cols = {row[1] for row in cursor.fetchall()}
            for col in ["origin_tc", "destination_tc"]:
                if col not in route_cols:
                    cursor.execute(f"ALTER TABLE routes ADD COLUMN {col} TEXT")
                    logger.info(f"Added column routes.{col}")
            cursor.execute("PRAGMA table_info(stops)")
            stop_cols = {row[1] for row in cursor.fetchall()}
            if "stop_name_tc" not in stop_cols:
                cursor.execute("ALTER TABLE stops ADD COLUMN stop_name_tc TEXT")
                logger.info("Added column stops.stop_name_tc")
            conn.commit()
    except sqlite3.OperationalError as e:
        logger.debug(f"Schema migration skipped: {e}")


def load_traffic_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load traffic route and stop data from database."""
    _ensure_schema_columns()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            routes_query = """
                SELECT DISTINCT route_id, route_name,
                    origin_en as origin, destination_en as destination,
                    COALESCE(origin_tc, '') as origin_tc,
                    COALESCE(destination_tc, '') as destination_tc,
                    service_type, company
                FROM routes ORDER BY route_id
            """
            routes_df = pd.read_sql_query(routes_query, conn)
            routes_df["route_type"] = routes_df.apply(classify_route_type, axis=1)

            stops_query = """
                SELECT stop_id, stop_name_en as stop_name,
                    COALESCE(stop_name_tc, '') as stop_name_tc, lat, lng, company
                FROM stops ORDER BY stop_id
            """
            stops_df = pd.read_sql_query(stops_query, conn)
            return routes_df, stops_df
    except Exception as e:
        err_msg = str(e).lower()
        if (
            "no such column" in err_msg
            or "origin_tc" in err_msg
            or "destination_tc" in err_msg
            or "stop_name_tc" in err_msg
        ):
            _ensure_schema_columns()
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    routes_df = pd.read_sql_query(
                        "SELECT DISTINCT route_id, route_name, origin_en as origin, destination_en as destination, "
                        "COALESCE(origin_tc,'') as origin_tc, COALESCE(destination_tc,'') as destination_tc, "
                        "service_type, company FROM routes ORDER BY route_id",
                        conn,
                    )
                    routes_df["route_type"] = routes_df.apply(
                        classify_route_type, axis=1
                    )
                    stops_df = pd.read_sql_query(
                        "SELECT stop_id, stop_name_en as stop_name, COALESCE(stop_name_tc,'') as stop_name_tc, "
                        "lat, lng, company FROM stops ORDER BY stop_id",
                        conn,
                    )
                return routes_df, stops_df
            except Exception:
                pass
            with sqlite3.connect(DB_PATH) as conn:
                routes_df = pd.read_sql_query(
                    "SELECT DISTINCT route_id, route_name, origin_en as origin, destination_en as destination, "
                    "'' as origin_tc, '' as destination_tc, service_type, company FROM routes ORDER BY route_id",
                    conn,
                )
                routes_df["route_type"] = routes_df.apply(classify_route_type, axis=1)
                stops_df = pd.read_sql_query(
                    "SELECT stop_id, stop_name_en as stop_name, '' as stop_name_tc, lat, lng, company FROM stops ORDER BY stop_id",
                    conn,
                )
            return routes_df, stops_df
        st.error(f"Error loading traffic data: {e}")
        logger.error(f"Database error: {e}")
        return pd.DataFrame(), pd.DataFrame()


def _get_special_route_type(indicator: str) -> str:
    m = {
        "X": "Express",
        "N": "Night",
        "P": "Peak",
        "A": "Airport",
        "E": "Airport",
        "S": "Special Service",
        "R": "Special Service",
    }
    return m.get(indicator, "Special")


def classify_route_type(route_row) -> str:
    route_id = str(route_row["route_id"]).upper()
    destination = str(route_row.get("destination", "")).upper()
    for ind in params["route_types"]["circular"]:
        if ind in destination:
            return "Circular"
    for ind in params["route_types"]["special"]:
        if route_id.endswith(ind):
            return _get_special_route_type(ind)
    return "Regular"


def _is_terminus_stop(name_en: str, name_tc: str) -> bool:
    """Check if stop is a bus terminus (總站)."""
    if not name_en and not name_tc:
        return False
    en = (name_en or "").upper()
    tc = name_tc or ""
    return "BUS TERMINUS" in en or "總站" in tc


def _reorder_circular_stops(dir_stops: pd.DataFrame, route_id: str) -> pd.DataFrame:
    """
    For circular routes, KMB API returns terminus last; bus actually starts at terminus.
    Reorder so terminus (last stop) becomes first.
    """
    if len(dir_stops) < 2:
        return dir_stops
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = pd.read_sql_query(
                "SELECT destination_en FROM routes WHERE route_id = ? LIMIT 1",
                conn,
                params=(route_id,),
            )
        dest = str(row.iloc[0]["destination_en"] or "") if not row.empty else ""
    except Exception:
        dest = ""
    route_type = classify_route_type({"route_id": route_id, "destination": dest})
    if route_type != "Circular":
        return dir_stops
    last_row = dir_stops.iloc[-1]
    if not _is_terminus_stop(
        last_row.get("stop_name", ""), last_row.get("stop_name_tc", "")
    ):
        return dir_stops
    # Rotate: last -> first, renumber sequence
    reordered = pd.concat(
        [dir_stops.iloc[[-1]], dir_stops.iloc[:-1]], ignore_index=True
    )
    reordered["sequence"] = range(1, len(reordered) + 1)
    return reordered


def prepare_direction_stops(
    route_stops: pd.DataFrame, direction: int, route_id: str
) -> pd.DataFrame:
    """Get direction stops sorted by sequence; for circular routes, terminus first."""
    dir_stops = route_stops[route_stops["direction"] == direction].sort_values(
        "sequence"
    )
    return _reorder_circular_stops(dir_stops, route_id)


def load_all_route_stops() -> dict[str, pd.DataFrame]:
    """Load all route_stops in one query. Returns {route_id: DataFrame} for instant lookup."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query(
                """
                SELECT rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                    COALESCE(s.stop_name_tc, '') as stop_name_tc, s.lat, s.lng,
                    rs.sequence, rs.direction, rs.service_type, s.company
                FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                ORDER BY rs.route_id, rs.direction, rs.sequence
                """,
                conn,
            )
            if "stop_name_tc" not in df.columns:
                df["stop_name_tc"] = ""
            return {rid: group for rid, group in df.groupby("route_id")}
    except sqlite3.OperationalError:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query(
                """
                SELECT rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                    '' as stop_name_tc, s.lat, s.lng, rs.sequence, rs.direction,
                    rs.service_type, s.company
                FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                ORDER BY rs.route_id, rs.direction, rs.sequence
                """,
                conn,
            )
            return {rid: group for rid, group in df.groupby("route_id")}
    except Exception as e:
        logger.error(f"Error loading all route stops: {e}")
        return {}


def get_route_stops_with_directions(route_id: str) -> pd.DataFrame:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query(
                """
                SELECT rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                    COALESCE(s.stop_name_tc, '') as stop_name_tc, s.lat, s.lng,
                    rs.sequence, rs.direction, rs.service_type, s.company
                FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                WHERE rs.route_id = ? ORDER BY rs.direction, rs.sequence
                """,
                conn,
                params=(route_id,),
            )
            if "stop_name_tc" not in df.columns:
                df["stop_name_tc"] = ""
            return df
    except sqlite3.OperationalError:
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(
                """
                SELECT rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                    '' as stop_name_tc, s.lat, s.lng, rs.sequence, rs.direction,
                    rs.service_type, s.company
                FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                WHERE rs.route_id = ? ORDER BY rs.direction, rs.sequence
                """,
                conn,
                params=(route_id,),
            )
    except Exception as e:
        logger.error(f"Error fetching route stops for {route_id}: {e}")
        return pd.DataFrame()


def get_route_directions_with_depots(route_id: str) -> list[dict[str, Any]]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            try:
                route_info = pd.read_sql_query(
                    "SELECT origin_en, destination_en, origin_tc, destination_tc FROM routes WHERE route_id = ?",
                    conn,
                    params=(route_id,),
                )
            except sqlite3.OperationalError:
                route_info = pd.read_sql_query(
                    "SELECT origin_en, destination_en FROM routes WHERE route_id = ?",
                    conn,
                    params=(route_id,),
                )
                route_info["origin_tc"] = route_info["destination_tc"] = ""
            if route_info.empty:
                return []
            r = route_info.iloc[0]
            origin, destination = r["origin_en"], r["destination_en"]
            otc, dtc = str(r.get("origin_tc", "") or ""), str(
                r.get("destination_tc", "") or ""
            )

            def _depot(o: str, d: str, oc: str, dc: str) -> str:
                en = f"{o} → {d}"
                if oc and dc:
                    return f"{en} ({oc} → {dc})"
                return en

            route_type = classify_route_type(
                {"route_id": route_id, "destination": destination}
            )
            dirs_df = pd.read_sql_query(
                "SELECT DISTINCT direction, COUNT(*) as stop_count FROM route_stops WHERE route_id = ? GROUP BY direction ORDER BY direction",
                conn,
                params=(route_id,),
            )
            # For circular routes, use actual first/last stop from route_stops (routes table can be wrong)
            circular_endpoints = {}
            if route_type == "Circular":
                ep_df = pd.read_sql_query(
                    """
                    SELECT rs.direction, rs.sequence, s.stop_name_en as name_en, COALESCE(s.stop_name_tc,'') as name_tc
                    FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                    WHERE rs.route_id = ?
                    """,
                    conn,
                    params=(route_id,),
                )
                for d in ep_df["direction"].unique():
                    dd = ep_df[ep_df["direction"] == d]
                    first_row = dd.loc[dd["sequence"].idxmin()]
                    last_row = dd.loc[dd["sequence"].idxmax()]
                    circular_endpoints[int(d)] = (
                        str(first_row["name_en"] or ""),
                        str(last_row["name_en"] or ""),
                        str(first_row["name_tc"] or ""),
                        str(last_row["name_tc"] or ""),
                    )

            directions = []
            for _, row in dirs_df.iterrows():
                d, cnt = int(row["direction"]), row["stop_count"]
                if route_type == "Circular":
                    if d in circular_endpoints:
                        first_en, last_en, first_tc, last_tc = circular_endpoints[d]
                        # KMB API has terminus last; bus starts at terminus, so swap for display
                        depot_name = (
                            _depot(last_en, first_en, last_tc, first_tc) + " (Circular)"
                        )
                    else:
                        depot_name = (
                            _depot(origin, destination, otc, dtc) + " (Circular)"
                        )
                    name = "Circular"
                elif d == 1:
                    depot_name = _depot(origin, destination, otc, dtc)
                    name = "Outbound"
                else:
                    depot_name = _depot(destination, origin, dtc, otc)
                    name = "Inbound"
                directions.append(
                    {"direction": d, "name": name, "depot": depot_name, "stops": cnt}
                )
            return directions
    except Exception as e:
        logger.error(f"Error getting directions for {route_id}: {e}")
        return []


def natural_sort_key(route_id: str) -> tuple[int, int, str]:
    """Sort: 1, 1A, 1X... then 2, 2A... (group by number, pure number first then letter variants)."""
    m = re.match(r"(\d+)(.*)", str(route_id))
    if m:
        num, suffix = int(m.group(1)), m.group(2)
        has_suffix = 1 if suffix else 0  # 0 = pure number first within group
        return (num, has_suffix, suffix)
    return (0, 0, str(route_id))


def get_sorted_routes(routes_df: pd.DataFrame) -> pd.DataFrame:
    df = routes_df.copy()
    df["sort_key"] = df["route_id"].apply(natural_sort_key)
    return df.sort_values("sort_key").drop("sort_key", axis=1)


def search_routes_with_directions(
    routes_df: pd.DataFrame, search_term: str
) -> list[dict[str, Any]]:
    if not search_term:
        return []
    mask = (
        routes_df["route_id"].str.contains(search_term, case=False, na=False)
        | routes_df["origin"].str.contains(search_term, case=False, na=False)
        | routes_df["destination"].str.contains(search_term, case=False, na=False)
    )
    results = []
    for _, route in routes_df[mask].iterrows():
        for di in get_route_directions_with_depots(route["route_id"]):
            results.append(
                {
                    "route_id": route["route_id"],
                    "route_type": route["route_type"],
                    "direction": di["direction"],
                    "direction_name": di["name"],
                    "depot_name": di["depot"],
                    "stop_count": di["stops"],
                    "display_text": f"{route['route_id']} - {di['depot']} ({di['name']}, {di['stops']} stops) [{route['route_type']}]",
                }
            )
    return results


def _seg_key(seg: list[tuple[float, float]]) -> tuple:
    """Cache key for segment (rounded coords) - same inter-stops = reuse."""
    return tuple((round(c[0], 5), round(c[1], 5)) for c in seg)


def get_osm_route_with_waypoints(
    stops_coords: list[tuple[float, float]],
    max_waypoints: int = MAX_WAYPOINTS,
    segment_cache: Optional[dict] = None,
    segment_lock: Optional[Any] = None,
    on_api_call: Optional[Callable[[], None]] = None,
) -> list[list[float]]:
    """
    Build route geometry using OSRM. Uses batched waypoints. When segment_cache
    is provided (precompute), reuses routing for identical stop sequences.
    """
    import time as _time

    if len(stops_coords) < MIN_STOPS_FOR_ROUTE:
        return []
    batch = min(8, max(2, max_waypoints))

    def _get_cached(key):
        if segment_cache is None:
            return None
        if segment_lock:
            with segment_lock:
                return segment_cache.get(key)
        return segment_cache.get(key)

    def _set_cached(key, val):
        if segment_cache and val and segment_lock:
            with segment_lock:
                segment_cache[key] = val
        elif segment_cache and val:
            segment_cache[key] = val

    if len(stops_coords) <= batch:
        key = _seg_key(stops_coords)
        cached = _get_cached(key)
        if cached is not None:
            return cached
        route = get_single_osm_route(stops_coords)
        result = route if route else [[lat, lng] for lat, lng in stops_coords]
        _set_cached(key, result if route else None)
        if on_api_call:
            on_api_call()
        return result
    all_coords = []
    i = 0
    while i < len(stops_coords) - 1:
        end = min(i + batch, len(stops_coords))
        seg = stops_coords[i:end]
        key = _seg_key(seg)
        route = _get_cached(key)
        if route is None:
            route = get_single_osm_route(seg)
            _set_cached(key, route)
            if on_api_call:
                on_api_call()
        if route:
            all_coords.extend(route if i == 0 else route[1:])
        else:
            all_coords.extend([[lat, lng] for lat, lng in (seg if i == 0 else seg[1:])])
        i = end - 1
        if i < len(stops_coords) - 1:
            _time.sleep(0.02)
    return all_coords


def get_single_osm_route(
    stops_coords: list[tuple[float, float]],
) -> Optional[list[list[float]]]:
    """Get road-following route from OSRM (driving profile). Falls back to straight line if API fails."""
    import time as _time

    retries = params.get("osm", {}).get("retry_attempts", 2) + 1
    timeout_sec = max(15, OSM_TIMEOUT)
    coords_str = ";".join([f"{lng},{lat}" for lat, lng in stops_coords])
    url = f"{OSM_BASE_URL}/{coords_str}?overview=full&geometries=geojson"
    for attempt in range(retries):
        try:
            r = requests.get(
                url, timeout=timeout_sec, headers={"User-Agent": "YuuTraffic/1.0"}
            )
            if r.status_code == HTTP_OK:
                data = r.json()
                if data.get("code") == "Ok" and data.get("routes"):
                    geom = data["routes"][0].get("geometry")
                    if geom and geom.get("coordinates"):
                        return [[c[1], c[0]] for c in geom["coordinates"]]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.debug(
                f"OSM routing attempt {attempt + 1} failed (timeout/connection): {e}"
            )
        except Exception as e:
            logger.debug(f"OSM routing attempt {attempt + 1} failed: {e}")
        if attempt < retries - 1:
            _time.sleep(1.0)
    return None


def _stops_hash(dir_stops: pd.DataFrame) -> str:
    """Hash of stop sequence for 智能 detection - same stops = use cache."""
    import hashlib

    ids = dir_stops["stop_id"].astype(str).tolist()
    seq = dir_stops["sequence"].astype(int).tolist()
    data = ",".join(f"{s}:{i}" for s, i in zip(ids, seq))
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _load_geometry_cache() -> dict:
    """Load precomputed route geometry from JSON cache."""
    import json
    from pathlib import Path

    cache_path = params.get(
        "route_geometry_cache", "data/02_intermediate/route_geometry_cache.json"
    )
    path = Path(cache_path)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.debug("Geometry cache load failed: %s", e)
        return {}


@st.cache_data(ttl=3600)
def _get_geometry_cache() -> dict:
    return _load_geometry_cache()


def get_route_geometry_with_progress(
    route_stops: pd.DataFrame, direction: int, route_id: Optional[str] = None
) -> list[list[float]]:
    dir_stops = route_stops[route_stops["direction"] == direction].sort_values(
        "sequence"
    )
    if len(dir_stops) < MIN_STOPS_FOR_ROUTE:
        return []
    coords = [
        (s["lat"], s["lng"])
        for _, s in dir_stops.iterrows()
        if pd.notna(s["lat"]) and pd.notna(s["lng"])
    ]
    if len(coords) < MIN_STOPS_FOR_ROUTE:
        return [[lat, lng] for lat, lng in coords]
    cache_key = f"{route_id}_{int(direction)}" if route_id else None
    if cache_key:
        cache = _get_geometry_cache()
        entry = cache.get(cache_key)
        if entry:
            current_hash = _stops_hash(dir_stops)
            if isinstance(entry, dict):
                if entry.get("hash") == current_hash and entry.get("coords"):
                    return entry["coords"]
            else:
                return entry
    use_osm = params.get("osm", {}).get("use_osm_routing", True)
    if use_osm:
        if params.get("ui", {}).get("show_progress_bars"):
            prog = st.progress(0)
            txt = st.empty()
            txt.text(f"🗺️ Getting route through {len(coords)} stops...")
            prog.progress(0.3)
        all_coords = get_osm_route_with_waypoints(coords)
        if not all_coords:
            all_coords = [[lat, lng] for lat, lng in coords]
        if params.get("ui", {}).get("show_progress_bars"):
            prog.progress(1.0)
            time.sleep(1)
            prog.empty()
            txt.empty()
    else:
        all_coords = [[lat, lng] for lat, lng in coords]
    return all_coords


def _calculate_map_bounds(
    route_stops: pd.DataFrame, direction: int, selected_stop_id: Optional[str] = None
) -> tuple[float, float, int]:
    dir_stops = route_stops[route_stops["direction"] == direction]
    if not dir_stops.empty:
        lats, lngs = dir_stops["lat"].dropna(), dir_stops["lng"].dropna()
        if len(lats) and len(lngs):
            clat, clng = lats.mean(), lngs.mean()
            mr = max(lats.max() - lats.min(), lngs.max() - lngs.min())
            zoom = (
                11
                if mr > ZOOM_VERY_SPREAD
                else (
                    12
                    if mr > ZOOM_MODERATE_SPREAD
                    else (
                        13
                        if mr > ZOOM_SOME_SPREAD
                        else (
                            14
                            if mr > ZOOM_CLOSE
                            else 15
                            if mr > ZOOM_VERY_CLOSE
                            else 16
                        )
                    )
                )
            )
            if selected_stop_id and params["map"]["auto_zoom"]["enabled"]:
                zoom = min(zoom + 1, STOP_ZOOM)
            return clat, clng, zoom
    return HK_CENTER[0], HK_CENTER[1], DEFAULT_ZOOM


def _add_map_controls(
    m: folium.Map,
    route_center: Optional[tuple[float, float, int]] = None,
    lang: str = "en",
) -> None:
    """Add Reset Map, Center on Route, and Locate Me buttons to the map."""
    lat, lng, zoom = HK_CENTER[0], HK_CENTER[1], DEFAULT_ZOOM
    controls_html = []
    scripts = []
    top = 10
    # Center on Route button (visible when route is displayed)
    centre_label = "鎖定路線" if lang == "tc" else "Centre on Route"
    if route_center:
        rlat, rlng, rzoom = route_center
        controls_html.append(
            f'<div data-center-route style="position:fixed;top:{top}px;right:10px;width:150px;height:36px;background:#28a745;color:#fff;'
            f"border:2px solid #1e7e34;border-radius:6px;z-index:1001;font-size:13px;display:flex;"
            f"align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,0.2);"
            f'font-weight:bold;">📍 {centre_label}</div>'
        )
        scripts.append(
            f"""
        (function() {{
            var btn = document.querySelector('[data-center-route]');
            if (btn) btn.onclick = function() {{
                if (typeof L !== 'undefined' && L.Map) {{
                    for (var k in window) {{
                        try {{
                            if (window[k] && window[k].setView && window[k].getZoom) {{
                                window[k].setView([{rlat}, {rlng}], {rzoom});
                                break;
                            }}
                        }} catch(e) {{}}
                    }}
                }}
            }};
        }})();
        """
        )
        top += 44
    # Reset Map button
    controls_html.append(
        f'<div data-reset-map style="position:fixed;top:{top}px;right:10px;width:140px;height:36px;background:#fff;'
        f"border:2px solid #1f77b4;border-radius:6px;z-index:1000;font-size:13px;display:flex;"
        f"align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,0.2);"
        f'font-weight:bold;">🔄 Reset Map</div>'
    )
    scripts.append(
        f"""
    (function() {{
        var btn = document.querySelector('[data-reset-map]');
        if (btn) btn.onclick = function() {{
            if (typeof L !== 'undefined' && L.Map) {{
                for (var k in window) {{
                    try {{
                        if (window[k] && window[k].setView && window[k].getZoom) {{
                            window[k].setView([{lat}, {lng}], {zoom});
                            break;
                        }}
                    }} catch(e) {{}}
                }}
            }}
        }};
    }})();
    """
    )
    combined = "".join(controls_html) + "<script>" + "".join(scripts) + "</script>"
    m.get_root().html.add_child(folium.Element(combined))
    LocateControl(
        auto_start=False,
        strings={"title": "Locate me", "popup": "You are here"},
    ).add_to(m)


def create_enhanced_route_map(
    route_stops: pd.DataFrame,
    selected_stop_id: Optional[str] = None,
    direction: int = 1,
    eta_dict: Optional[dict[str, list[str]]] = None,
    lang: str = "en",
) -> folium.Map:
    eta_dict = eta_dict or {}
    clat, clng, zoom = _calculate_map_bounds(route_stops, direction, selected_stop_id)
    tiles_cfg = params.get("map", {})
    tiles_url = tiles_cfg.get("tiles_url")
    if tiles_url:
        m = folium.Map(location=[clat, clng], zoom_start=zoom, tiles=None)
        folium.TileLayer(
            tiles=tiles_url,
            attr="Map data © OpenStreetMap",
            min_zoom=8,
            max_zoom=19,
        ).add_to(m)
    else:
        m = folium.Map(
            location=[clat, clng],
            zoom_start=zoom,
            tiles=tiles_cfg.get("tiles", "OpenStreetMap"),
        )
    route_center = (clat, clng, zoom) if not route_stops.empty else None
    _add_map_controls(m, route_center=route_center, lang=lang)
    if not route_stops.empty:
        route_id = (
            str(route_stops["route_id"].iloc[0])
            if "route_id" in route_stops.columns and not route_stops.empty
            else None
        )
        coords = get_route_geometry_with_progress(
            route_stops, direction, route_id=route_id
        )
        if len(coords) > 1:
            use_osm = params.get("osm", {}).get("use_osm_routing", True)
            folium.PolyLine(
                locations=coords,
                color="#1f77b4",
                weight=5,
                opacity=0.8,
                popup="Bus route",
                tooltip=(
                    "Route follows roads (OSRM driving)"
                    if use_osm
                    else "Stops connected (straight lines)"
                ),
            ).add_to(m)
        dir_stops = route_stops[route_stops["direction"] == direction].sort_values(
            "sequence"
        )
        for _, s in dir_stops.iterrows():
            if pd.notna(s["lat"]) and pd.notna(s["lng"]):
                stop_name = s["stop_name"]
                stop_tc = s.get("stop_name_tc", "") or ""
                if lang == "tc" and stop_tc:
                    popup_text = f"<b>{stop_tc}</b><br><span style='font-size:0.95em;'>{stop_name}</span>"
                elif stop_tc:
                    popup_text = f"<b>{stop_name}</b><br><span style='font-size:0.95em;'>{stop_tc}</span>"
                else:
                    popup_text = f"<b>{stop_name}</b>"
                popup_text += f"<br>Stop #{int(s['sequence'])}"
                etas = eta_dict.get(s["stop_id"], [])
                if etas:
                    popup_text += f"<br><span style='color:#28a745;font-weight:500;'>ETA: {', '.join(etas)}</span>"
                icon = (
                    folium.Icon(color="red", icon="star", prefix="fa")
                    if selected_stop_id and s["stop_id"] == selected_stop_id
                    else folium.Icon(color="blue", icon="bus", prefix="fa")
                )
                folium.Marker(
                    [s["lat"], s["lng"]],
                    popup=folium.Popup(popup_text, max_width=250),
                    icon=icon,
                ).add_to(m)
    return m


def format_route_type_badge(route_type: str) -> str:
    colors = {
        "Regular": "#28a745",
        "Express": "#fd7e14",
        "Circular": "#6f42c1",
        "Night": "#212529",
        "Peak": "#dc3545",
        "Airport": "#17a2b8",
        "Special Service": "#ffc107",
        "Special": "#6c757d",
    }
    c = colors.get(route_type, "#6c757d")
    return f'<span style="background:{c};color:white;padding:2px 6px;border-radius:3px;font-size:12px;font-weight:bold">{route_type}</span>'


def create_route_options(routes_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Create formatted route options for the selectbox (with Chinese when available)."""
    options = []
    for _, route in routes_df.iterrows():
        try:
            origin, destination = route["origin"], route["destination"]
        except KeyError:
            origin, destination = route["origin_en"], route["destination_en"]
        otc = route.get("origin_tc", "") or ""
        dtc = route.get("destination_tc", "") or ""
        route_type = route.get("route_type", "Regular")
        text = f"{route['route_id']} - {origin} → {destination}"
        if otc and dtc:
            text += f" ({otc} → {dtc})"
        text += f" [{route_type}]"
        options.append(
            {
                "text": text,
                "route_id": route["route_id"],
                "origin": origin,
                "destination": destination,
                "origin_tc": otc,
                "destination_tc": dtc,
                "route_type": route_type,
            }
        )
    return options


def create_route_options_with_directions(
    routes_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Create route options including direction - one option per (route_id, direction)."""
    options = []
    for _, route in routes_df.iterrows():
        try:
            origin, destination = route["origin"], route["destination"]
        except KeyError:
            origin, destination = route["origin_en"], route["destination_en"]
        otc = route.get("origin_tc", "") or ""
        dtc = route.get("destination_tc", "") or ""
        route_type = route.get("route_type", "Regular")
        for di in get_route_directions_with_depots(route["route_id"]):
            depot = di["depot"]
            dir_num = di["direction"]
            stops_cnt = di["stops"]
            text = f"{route['route_id']} - {depot} (Dir {dir_num}, {stops_cnt} stops) [{route_type}]"
            options.append(
                {
                    "text": text,
                    "route_id": route["route_id"],
                    "direction": dir_num,
                    "origin": origin,
                    "destination": destination,
                    "origin_tc": otc,
                    "destination_tc": dtc,
                    "route_type": route_type,
                    "depot_name": depot,
                    "stop_count": stops_cnt,
                }
            )
    return options


def _eta_to_minutes_from_now(ts_str: str) -> str:
    """Convert ETA timestamp to 'X min' format like KMB app."""
    try:
        from zoneinfo import ZoneInfo

        hk = ZoneInfo("Asia/Hong_Kong")
    except ImportError:
        hk = timezone(timedelta(hours=8))
    try:
        ts_clean = str(ts_str).replace("Z", "+00:00")
        eta_dt = datetime.fromisoformat(ts_clean)
        if eta_dt.tzinfo is None:
            eta_dt = eta_dt.replace(tzinfo=hk)
        now = datetime.now(hk)
        mins = int((eta_dt - now).total_seconds() / 60)
        if mins < 0:
            return "Arriving" if mins >= -2 else "—"
        if mins == 0:
            return "1 min"
        return f"{mins} min"
    except Exception:
        return str(ts_str)[:5] if len(str(ts_str)) >= 5 else str(ts_str)


def fetch_etas_for_stops(
    route_id: str,
    stop_ids: list[str],
    service_type: int = 1,
    max_stops: int = 20,
    minutes_format: bool = True,
) -> dict[str, list[str]]:
    """
    Fetch real-time ETAs from KMB API for given stops.
    Returns {stop_id: [eta1, eta2, eta3]} - either 'X min' or 'HH:MM' per minutes_format.
    """
    import time as _time

    base_url = params.get("api", {}).get(
        "kmb_base_url", "https://data.etabus.gov.hk/v1/transport/kmb"
    )
    result: dict[str, list[str]] = {}
    stops = stop_ids[:max_stops]
    for i, stop_id in enumerate(stops):
        try:
            url = f"{base_url}/eta/{stop_id}/{route_id}/{service_type}"
            r = requests.get(
                url,
                timeout=8,
                headers={"User-Agent": "YuuTraffic/1.0", "Accept": "application/json"},
            )
            if r.status_code != HTTP_OK:
                continue
            data = r.json()
            entries = data.get("data", [])
            if not isinstance(entries, list):
                entries = [entries] if entries else []
            etas = []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                ts = (
                    e.get("eta")
                    or e.get("arrival_time")
                    or e.get("eta_seq1")
                    or e.get("eta_seq2")
                    or e.get("eta_seq3")
                )
                if ts:
                    if minutes_format:
                        etas.append(_eta_to_minutes_from_now(ts))
                    else:
                        try:
                            ts_clean = str(ts).replace("Z", "+00:00")
                            etas.append(
                                datetime.fromisoformat(ts_clean).strftime("%H:%M")
                            )
                        except Exception:
                            etas.append(str(ts)[:5] if len(str(ts)) >= 5 else str(ts))
            if etas:
                result[stop_id] = etas[:3]
        except Exception as e:
            logger.debug(f"ETA fetch {stop_id}: {e}")
        if i < len(stops) - 1:
            _time.sleep(0.15)
    return result


def get_first_run_status() -> bool:
    return not os.path.exists("data/.first_run_complete")


def mark_first_run_complete():
    os.makedirs("data", exist_ok=True)
    with open("data/.first_run_complete", "w") as f:
        f.write("First run completed")


def should_update_data() -> bool:
    if get_first_run_status():
        return True
    if params.get("schedule", {}).get("daily_update", {}).get("enabled"):
        return True  # Simplified: always allow update when enabled
    return False
