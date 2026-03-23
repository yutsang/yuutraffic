"""
Web app logic: data loading, route mapping, search.
"""

import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

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
            for col in ["origin_tc", "destination_tc", "provider_route_id"]:
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


def _infer_route_region(
    origin: str, destination: str, origin_tc: str, destination_tc: str
) -> str:
    """Infer primary region (HKL/KLN/NT) from route endpoints. HKL=HK Island, KLN=Kowloon, NT=New Territories."""

    def _check(s: str) -> tuple[bool, bool, bool]:
        s = (s or "").upper()
        hkl = any(
            x in s
            for x in (
                "CENTRAL",
                "WAN CHAI",
                "CAUSEWAY BAY",
                "NORTH POINT",
                "SHAU KEI WAN",
                "CHAI WAN",
                "ABERDEEN",
                "PEAK",
                "黎樂",
                "灣仔",
                "銅鑼灣",
                "北角",
                "筲箕灣",
                "柴灣",
            )
        )
        kln = any(
            x in s
            for x in (
                "TSIM SHA TSUI",
                "MONG KOK",
                "KWUN TONG",
                "YAU MA TEI",
                "JORDAN",
                "SHAM SHUI PO",
                "CHOI HUNG",
                "尖沙咀",
                "旺角",
                "觀塘",
                "油麻地",
                "佐敦",
                "深水埗",
            )
        )
        nt = any(
            x in s
            for x in (
                "TIN SHUI WAI",
                "YUEN LONG",
                "SHA TIN",
                "TAI PO",
                "TUEN MUN",
                "天水圍",
                "元朗",
                "沙田",
                "大埔",
                "屯門",
            )
        )
        return (hkl, kln, nt)

    o_en, o_tc = (origin or "").upper(), (origin_tc or "")
    d_en, d_tc = (destination or "").upper(), (destination_tc or "")
    oh, ok, on = _check(o_en + " " + o_tc)
    dh, dk, dn = _check(d_en + " " + d_tc)
    if oh or dh:
        return "HKL"
    if ok or dk:
        return "KLN"
    if on or dn:
        return "NT"
    return "KLN"  # default


def load_traffic_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load traffic route and stop data from database."""
    _ensure_schema_columns()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            try:
                routes_query = """
                    SELECT DISTINCT route_key, route_id, route_name,
                        origin_en as origin, destination_en as destination,
                        COALESCE(origin_tc, '') as origin_tc,
                        COALESCE(destination_tc, '') as destination_tc,
                        service_type, company,
                        COALESCE(provider_route_id, '') as provider_route_id,
                        geometry_hash, last_precomputed_at
                    FROM routes ORDER BY route_key
                """
                routes_df = pd.read_sql_query(routes_query, conn)
            except sqlite3.OperationalError:
                routes_query = """
                    SELECT DISTINCT route_id as route_key, route_id, route_name,
                        origin_en as origin, destination_en as destination,
                        COALESCE(origin_tc, '') as origin_tc,
                        COALESCE(destination_tc, '') as destination_tc,
                        service_type, company,
                        '' as provider_route_id,
                        NULL as geometry_hash, NULL as last_precomputed_at
                    FROM routes ORDER BY route_id
                """
                routes_df = pd.read_sql_query(routes_query, conn)
            routes_df["route_type"] = routes_df.apply(classify_route_type, axis=1)
            routes_df["region"] = routes_df.apply(
                lambda r: _infer_route_region(
                    r.get("origin"),
                    r.get("destination"),
                    r.get("origin_tc", ""),
                    r.get("destination_tc", ""),
                ),
                axis=1,
            )

            stops_query = """
                SELECT stop_id, stop_name_en as stop_name,
                    COALESCE(stop_name_tc, '') as stop_name_tc, lat, lng, company
                FROM stops ORDER BY stop_id
            """
            stops_df = pd.read_sql_query(stops_query, conn)
            return routes_df, stops_df
    except sqlite3.OperationalError as e:
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
                        "SELECT DISTINCT route_id as route_key, route_id, route_name, origin_en as origin, destination_en as destination, "
                        "COALESCE(origin_tc,'') as origin_tc, COALESCE(destination_tc,'') as destination_tc, "
                        "service_type, company, geometry_hash, last_precomputed_at FROM routes ORDER BY route_id",
                        conn,
                    )
                    routes_df["route_type"] = routes_df.apply(
                        classify_route_type, axis=1
                    )
                    routes_df["region"] = routes_df.apply(
                        lambda r: _infer_route_region(
                            r.get("origin"),
                            r.get("destination"),
                            r.get("origin_tc", ""),
                            r.get("destination_tc", ""),
                        ),
                        axis=1,
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
                    "SELECT DISTINCT route_id as route_key, route_id, route_name, origin_en as origin, destination_en as destination, "
                    "'' as origin_tc, '' as destination_tc, service_type, company, NULL as geometry_hash, NULL as last_precomputed_at FROM routes ORDER BY route_id",
                    conn,
                )
                routes_df["route_type"] = routes_df.apply(classify_route_type, axis=1)
                routes_df["region"] = "KLN"
                stops_df = pd.read_sql_query(
                    "SELECT stop_id, stop_name_en as stop_name, '' as stop_name_tc, lat, lng, company FROM stops ORDER BY stop_id",
                    conn,
                )
            return routes_df, stops_df
    except Exception as e:
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
    comp = str(route_row.get("company", "") or "").upper()
    if "GMB" in comp or "GREEN MINIBUS" in comp:
        return "Green Minibus"
    if "MTR" in comp and "BUS" in comp:
        return "MTR Bus"
    if "RMB" in comp or ("RED" in comp and "MINIBUS" in comp):
        return "Red Minibus"
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


def _reorder_circular_stops(dir_stops: pd.DataFrame, route_key: str) -> pd.DataFrame:
    """
    For circular routes, KMB API returns terminus last; bus actually starts at terminus.
    Reorder so terminus (last stop) becomes first.
    """
    if len(dir_stops) < 2:
        return dir_stops
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = pd.read_sql_query(
                "SELECT destination_en FROM routes WHERE route_key = ? OR route_id = ? LIMIT 1",
                conn,
                params=(route_key, route_key),
            )
        dest = str(row.iloc[0]["destination_en"] or "") if not row.empty else ""
    except Exception:
        dest = ""
    route_type = classify_route_type({"route_id": route_key, "destination": dest})
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


def _enrich_mtr_bus_stops(dir_stops: pd.DataFrame) -> pd.DataFrame:
    """MTR Bus API has no stop names/coords in JSON — fill labels and map positions."""
    if dir_stops.empty or "company" not in dir_stops.columns:
        return dir_stops
    comp = str(dir_stops["company"].iloc[0] or "")
    if "MTR" not in comp.upper() or "BUS" not in comp.upper():
        return dir_stops
    try:
        from .mtr_bus_geo import enrich_mtr_stop_row, mtr_bus_stop_leg
    except ImportError:
        return dir_stops
    rid = str(dir_stops["route_id"].iloc[0]) if "route_id" in dir_stops.columns else ""
    n = len(dir_stops)
    out = dir_stops.copy()
    for i, idx in enumerate(out.index):
        row = out.loc[idx]
        seq = int(row.get("sequence", i + 1))
        sid = str(row.get("stop_id", ""))
        leg = mtr_bus_stop_leg(sid)
        en, tc, lat, lng = enrich_mtr_stop_row(rid, sid, seq, n, leg)
        out.loc[idx, "stop_name"] = en
        out.loc[idx, "stop_name_tc"] = tc
        out.loc[idx, "lat"] = lat
        out.loc[idx, "lng"] = lng
    return out


def prepare_direction_stops(
    route_stops: pd.DataFrame, direction: int, route_key: str
) -> pd.DataFrame:
    """Get direction stops sorted by sequence; for circular routes, terminus first."""
    dir_stops = route_stops[route_stops["direction"] == direction].sort_values(
        "sequence"
    )
    dir_stops = _reorder_circular_stops(dir_stops, route_key)
    return _enrich_mtr_bus_stops(dir_stops)


def load_all_route_stops() -> dict[str, pd.DataFrame]:
    """Load all route_stops in one query. Returns {route_key: DataFrame} for instant lookup."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            try:
                df = pd.read_sql_query(
                    """
                    SELECT COALESCE(rs.route_key, rs.route_id) as route_key, rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                        COALESCE(s.stop_name_tc, '') as stop_name_tc, s.lat, s.lng,
                        rs.sequence, rs.direction, rs.service_type, s.company
                    FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                    ORDER BY COALESCE(rs.route_key, rs.route_id), rs.direction, rs.sequence
                    """,
                    conn,
                )
            except sqlite3.OperationalError:
                df = pd.read_sql_query(
                    """
                    SELECT rs.route_id as route_key, rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                        COALESCE(s.stop_name_tc, '') as stop_name_tc, s.lat, s.lng,
                        rs.sequence, rs.direction, rs.service_type, s.company
                    FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                    ORDER BY rs.route_id, rs.direction, rs.sequence
                    """,
                    conn,
                )
            if "stop_name_tc" not in df.columns:
                df["stop_name_tc"] = ""
            return {rid: group for rid, group in df.groupby("route_key")}
    except sqlite3.OperationalError:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query(
                """
                SELECT rs.route_id as route_key, rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                    '' as stop_name_tc, s.lat, s.lng, rs.sequence, rs.direction,
                    rs.service_type, s.company
                FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                ORDER BY rs.route_id, rs.direction, rs.sequence
                """,
                conn,
            )
            return {rid: group for rid, group in df.groupby("route_key")}
    except Exception as e:
        logger.error(f"Error loading all route stops: {e}")
        return {}


def get_route_stops_with_directions(route_key: str) -> pd.DataFrame:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            try:
                df = pd.read_sql_query(
                    """
                    SELECT COALESCE(rs.route_key, rs.route_id) as route_key, rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                        COALESCE(s.stop_name_tc, '') as stop_name_tc, s.lat, s.lng,
                        rs.sequence, rs.direction, rs.service_type, s.company
                    FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                    WHERE rs.route_key = ? OR rs.route_id = ? ORDER BY rs.direction, rs.sequence
                    """,
                    conn,
                    params=(route_key, route_key),
                )
            except sqlite3.OperationalError:
                df = pd.read_sql_query(
                    """
                    SELECT rs.route_id as route_key, rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                        COALESCE(s.stop_name_tc, '') as stop_name_tc, s.lat, s.lng,
                        rs.sequence, rs.direction, rs.service_type, s.company
                    FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                    WHERE rs.route_id = ? ORDER BY rs.direction, rs.sequence
                    """,
                    conn,
                    params=(route_key,),
                )
            if "stop_name_tc" not in df.columns:
                df["stop_name_tc"] = ""
            return df
    except sqlite3.OperationalError:
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(
                """
                SELECT rs.route_id as route_key, rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                    '' as stop_name_tc, s.lat, s.lng, rs.sequence, rs.direction,
                    rs.service_type, s.company
                FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                WHERE rs.route_id = ? ORDER BY rs.direction, rs.sequence
                """,
                conn,
                params=(route_key,),
            )
    except Exception as e:
        logger.error(f"Error fetching route stops for {route_key}: {e}")
        return pd.DataFrame()


def get_all_route_directions_bulk(
    routes_df: pd.DataFrame,
) -> dict[str, list[dict[str, Any]]]:
    """Bulk fetch directions for all routes (few queries vs N per route). Returns {route_key: [dir_info...]}."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            route_keys = routes_df["route_key"].dropna().unique().tolist()
            if not route_keys:
                return {}
            batch_size = 500
            routes_info_list = []
            dirs_list = []
            ep_list = []
            for i in range(0, len(route_keys), batch_size):
                chunk = route_keys[i : i + batch_size]
                ph = ",".join("?" * len(chunk))
                routes_info_list.append(
                    pd.read_sql_query(
                        f"""SELECT route_key, route_id, origin_en, destination_en,
                            COALESCE(origin_tc,'') as origin_tc, COALESCE(destination_tc,'') as destination_tc
                            FROM routes WHERE route_key IN ({ph})""",
                        conn,
                        params=chunk,
                    )
                )
                dirs_list.append(
                    pd.read_sql_query(
                        f"""SELECT COALESCE(route_key, route_id) as rk, direction, COUNT(*) as stop_count
                            FROM route_stops WHERE COALESCE(route_key, route_id) IN ({ph})
                            GROUP BY rk, direction ORDER BY rk, direction""",
                        conn,
                        params=chunk,
                    )
                )
                try:
                    ep_list.append(
                        pd.read_sql_query(
                            f"""SELECT COALESCE(rs.route_key, rs.route_id) as rk, rs.direction, rs.sequence,
                                s.stop_name_en as name_en, COALESCE(s.stop_name_tc,'') as name_tc
                                FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                                WHERE COALESCE(rs.route_key, rs.route_id) IN ({ph})""",
                            conn,
                            params=chunk,
                        )
                    )
                except sqlite3.OperationalError:
                    ep_list.append(pd.DataFrame())
            routes_info = (
                pd.concat(routes_info_list, ignore_index=True)
                if routes_info_list
                else pd.DataFrame()
            )
            dirs_df = (
                pd.concat(dirs_list, ignore_index=True) if dirs_list else pd.DataFrame()
            )
            ep_df = pd.concat(ep_list, ignore_index=True) if ep_list else pd.DataFrame()
            routes_by_key = {}
            if not routes_info.empty and "route_key" in routes_info.columns:
                for _, row in routes_info.iterrows():
                    rk = row.get("route_key") or row.get("route_id")
                    if rk is not None:
                        routes_by_key[str(rk)] = dict(row)
            dirs_by_route = dirs_df.groupby("rk")
            circular_first_last = {}
            if not ep_df.empty:
                for (rk, d), grp in ep_df.groupby(["rk", "direction"]):
                    first_row = grp.loc[grp["sequence"].idxmin()]
                    last_row = grp.loc[grp["sequence"].idxmax()]
                    if isinstance(first_row, pd.Series) and isinstance(
                        last_row, pd.Series
                    ):
                        circular_first_last[(rk, int(d))] = (
                            str(first_row.get("name_en", "") or ""),
                            str(last_row.get("name_en", "") or ""),
                            str(first_row.get("name_tc", "") or ""),
                            str(last_row.get("name_tc", "") or ""),
                        )
            result = {}
            for rk in route_keys:
                r = routes_by_key.get(rk, {})
                if not r or not isinstance(r, dict):
                    result[rk] = []
                    continue
                origin = r.get("origin_en", "")
                destination = r.get("destination_en", "")
                otc = r.get("origin_tc", "") or ""
                dtc = r.get("destination_tc", "") or ""

                def _depot(o: str, d: str, oc: str, dc: str) -> str:
                    en = f"{o} → {d}"
                    if oc and dc:
                        return f"{en} ({oc} → {dc})"
                    return en

                route_type = classify_route_type(
                    {"route_id": rk, "destination": destination}
                )
                try:
                    grp = dirs_by_route.get_group(rk)
                except KeyError:
                    grp = pd.DataFrame()
                dirs = []
                for _, row in grp.iterrows():
                    d, cnt = int(row["direction"]), row["stop_count"]
                    if route_type == "Circular":
                        key = (rk, d)
                        if key in circular_first_last:
                            first_en, last_en, first_tc, last_tc = circular_first_last[
                                key
                            ]
                            depot_name = (
                                _depot(last_en, first_en, last_tc, first_tc)
                                + " (Circular)"
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
                    dirs.append(
                        {
                            "direction": d,
                            "name": name,
                            "depot": depot_name,
                            "stops": cnt,
                        }
                    )
                result[rk] = dirs
            return result
    except Exception:
        logger.exception("Bulk directions failed")
        return {}


def get_route_directions_with_depots(route_key: str) -> list[dict[str, Any]]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            try:
                route_info = pd.read_sql_query(
                    "SELECT origin_en, destination_en, origin_tc, destination_tc FROM routes WHERE route_key = ? OR route_id = ?",
                    conn,
                    params=(route_key, route_key),
                )
            except sqlite3.OperationalError:
                route_info = pd.read_sql_query(
                    "SELECT origin_en, destination_en FROM routes WHERE route_id = ?",
                    conn,
                    params=(route_key,),
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
                {"route_id": route_key, "destination": destination}
            )
            try:
                dirs_df = pd.read_sql_query(
                    "SELECT DISTINCT direction, COUNT(*) as stop_count FROM route_stops WHERE route_key = ? OR route_id = ? GROUP BY direction ORDER BY direction",
                    conn,
                    params=(route_key, route_key),
                )
            except sqlite3.OperationalError:
                dirs_df = pd.read_sql_query(
                    "SELECT DISTINCT direction, COUNT(*) as stop_count FROM route_stops WHERE route_id = ? GROUP BY direction ORDER BY direction",
                    conn,
                    params=(route_key,),
                )
            # For circular routes, use actual first/last stop from route_stops (routes table can be wrong)
            circular_endpoints = {}
            if route_type == "Circular":
                ep_df = pd.read_sql_query(
                    """
                    SELECT rs.direction, rs.sequence, s.stop_name_en as name_en, COALESCE(s.stop_name_tc,'') as name_tc
                    FROM route_stops rs JOIN stops s ON rs.stop_id = s.stop_id
                    WHERE rs.route_key = ? OR rs.route_id = ?
                    """,
                    conn,
                    params=(route_key, route_key),
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
        logger.error(f"Error getting directions for {route_key}: {e}")
        return []


def natural_sort_key(route_id: str) -> tuple[int, int, str]:
    """Sort: 1, 1A, 1X... then 2, 2A... (group by number, pure number first then letter variants)."""
    rid = str(route_id)
    if "-" in rid:
        prefix, rest = rid.split("-", 1)
        if prefix in ("HKI", "KLN", "NT"):
            reg_order = {"HKI": 0, "KLN": 1, "NT": 2}.get(prefix, 9)
            m = re.match(r"(\d+)(.*)", rest, re.I)
            if m:
                num, suffix = int(m.group(1)), m.group(2)
                has_suffix = 1 if suffix else 0
                return (reg_order, num, has_suffix, suffix)
            return (reg_order, 0, 0, rest)
    m = re.match(r"(\d+)(.*)", rid)
    if m:
        num, suffix = int(m.group(1)), m.group(2)
        has_suffix = 1 if suffix else 0  # 0 = pure number first within group
        return (0, num, has_suffix, suffix)
    return (0, 0, 0, rid)


def _company_sort_tier(company: str) -> int:
    c = str(company or "").upper()
    if "KMB" in c or "LWB" in c:
        return 0
    if "CTB" in c:
        return 1
    if "GMB" in c:
        return 2
    if "MTR" in c and "BUS" in c:
        return 3
    if "RMB" in c or ("RED" in c and "MINIBUS" in c):
        return 4
    return 5


def get_sorted_routes(routes_df: pd.DataFrame) -> pd.DataFrame:
    """Operator order (KMB → CTB → GMB → MTR Bus → red minibus), then sensible route number sort."""
    df = routes_df.copy()
    df["_tier"] = df["company"].apply(_company_sort_tier)
    df["_sort_key"] = df["route_id"].apply(natural_sort_key)
    df = df.sort_values(by=["_tier", "_sort_key"], kind="mergesort")
    return df.drop(columns=["_tier", "_sort_key"])


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
    segment_cache: dict | None = None,
    segment_lock: Any | None = None,
    on_api_call: Callable[[], None] | None = None,
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
) -> list[list[float]] | None:
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
    """Load precomputed route geometry from legacy single-file cache."""
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


def _get_geometry_entry(cache_key: str):
    """Get geometry for one route. Prefers per-route dir (editable), else legacy cache."""
    if params.get("route_geometry_dir"):
        from .precompute import load_route_entry

        entry = load_route_entry(cache_key)
        if entry and entry.get("coords"):
            return entry
        return None
    return _get_geometry_cache().get(cache_key)


def get_route_geometry_with_progress(
    route_stops: pd.DataFrame,
    direction: int,
    route_id: str | None = None,
    geometry_hash: str | None = None,
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
        entry = _get_geometry_entry(cache_key)
        if entry:
            # If we have a hash from DB, trust it for fast loading
            if geometry_hash and entry.get("hash") == geometry_hash:
                return entry.get("coords") or []

            # Fallback to file-based hash check
            if params.get("route_geometry_dir"):
                return entry.get("coords") or []

            current_hash = _stops_hash(dir_stops)
            if isinstance(entry, dict):
                if entry.get("hash") == current_hash and entry.get("coords"):
                    return entry["coords"]
            elif isinstance(entry, list):
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
    route_stops: pd.DataFrame, direction: int, selected_stop_id: str | None = None
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
                            else 15 if mr > ZOOM_VERY_CLOSE else 16
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
    route_center: tuple[float, float, int] | None = None,
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
        scripts.append(f"""
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
        """)
        top += 44
    # Reset Map button
    controls_html.append(
        f'<div data-reset-map style="position:fixed;top:{top}px;right:10px;width:140px;height:36px;background:#fff;'
        f"border:2px solid #1f77b4;border-radius:6px;z-index:1000;font-size:13px;display:flex;"
        f"align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,0.2);"
        f'font-weight:bold;">🔄 Reset Map</div>'
    )
    scripts.append(f"""
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
    """)
    combined = "".join(controls_html) + "<script>" + "".join(scripts) + "</script>"
    m.get_root().html.add_child(folium.Element(combined))
    LocateControl(
        auto_start=False,
        strings={"title": "Locate me", "popup": "You are here"},
    ).add_to(m)


def create_enhanced_route_map(
    route_stops: pd.DataFrame,
    selected_stop_id: str | None = None,
    direction: int = 1,
    eta_dict: dict[str, list[str]] | None = None,
    lang: str = "en",
    geometry_hash: str | None = None,
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
        # Use route_key (KMB_1, CTB_1) for cache lookup - matches precompute file names
        route_key = None
        if "route_key" in route_stops.columns:
            route_key = (
                str(route_stops["route_key"].iloc[0]) if not route_stops.empty else None
            )
        if not route_key and "route_id" in route_stops.columns:
            route_key = str(route_stops["route_id"].iloc[0])
        coords = get_route_geometry_with_progress(
            route_stops, direction, route_id=route_key, geometry_hash=geometry_hash
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
            lat_v = float(s["lat"]) if pd.notna(s["lat"]) else 0.0
            lng_v = float(s["lng"]) if pd.notna(s["lng"]) else 0.0
            if lat_v and lng_v and pd.notna(s["lat"]) and pd.notna(s["lng"]):
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
                    [lat_v, lng_v],
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
        "Green Minibus": "#20c997",
        "MTR Bus": "#9c27b0",
        "Red Minibus": "#e91e63",
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
    """Create route options including direction - one option per (route_key, direction).
    When same route_id exists for multiple companies (e.g. KMB 1 vs CTB 1), add region suffix (HKL/KLN) to differentiate.
    Uses bulk directions fetch for fast preloading and fetches geometry hashes from DB.
    """
    route_id_counts = {}
    if not routes_df.empty and "route_id" in routes_df.columns:
        route_id_counts = routes_df.groupby("route_id").size().to_dict()

    directions_map = get_all_route_directions_bulk(routes_df)

    def _company_short(c: str) -> str:
        u = str(c or "").upper()
        if "KMB" in u or "LWB" in u:
            return "KMB"
        if "CTB" in u:
            return "CTB"
        if "GMB" in u:
            return "GMB"
        if "MTR" in u and "BUS" in u:
            return "MTR"
        if "RMB" in u or ("RED" in u and "MINIBUS" in u):
            return "RMB"
        return (str(c) or "?")[:14]

    # Fetch all geometry hashes at once
    from .database_manager import KMBDatabaseManager

    db_manager = KMBDatabaseManager(DB_PATH, init_db=False)
    all_hashes = db_manager.get_route_geometry_hashes()

    options = []
    for _, route in routes_df.iterrows():
        try:
            origin, destination = route["origin"], route["destination"]
        except KeyError:
            origin, destination = route["origin_en"], route["destination_en"]
        otc = route.get("origin_tc", "") or ""
        dtc = route.get("destination_tc", "") or ""
        route_type = route.get("route_type", "Regular")
        route_key = route.get("route_key", route.get("route_id", ""))
        route_id = route.get("route_id", route_key)
        region = route.get("region", "KLN")
        comp = route.get("company", "") or ""
        prov = str(route.get("provider_route_id") or "").strip() or None
        co_short = _company_short(comp)
        dirs = directions_map.get(route_key, []) or get_route_directions_with_depots(
            route_key
        )
        if not dirs:
            depot = f"{origin} → {destination}".strip()
            if otc or dtc:
                depot = f"{depot} ({otc} → {dtc})".strip()
            if not depot.replace("→", "").strip():
                depot = "No stop list (reference route only)"
            dirs = [{"direction": 1, "name": "Listed", "depot": depot, "stops": 0}]

        for di in dirs:
            depot = di["depot"]
            dir_num = di["direction"]
            stops_cnt = di["stops"]
            rid_display = str(route_id)
            if route_id_counts.get(route_id, 1) > 1:
                rid_display = f"{route_id} · {region}"

            # Get hash for this specific (route, direction)
            geometry_hash = all_hashes.get((str(route_key), int(dir_num)))

            text = f"[{co_short}] {rid_display} — {depot} (dir {dir_num}, {stops_cnt} stops) · {route_type}"
            options.append(
                {
                    "text": text,
                    "route_key": route_key,
                    "route_id": route_id,
                    "display_route_id": rid_display,
                    "direction": dir_num,
                    "origin": origin,
                    "destination": destination,
                    "origin_tc": otc,
                    "destination_tc": dtc,
                    "route_type": route_type,
                    "depot_name": depot,
                    "stop_count": stops_cnt,
                    "company": comp,
                    "region": region,
                    "geometry_hash": geometry_hash,
                    "provider_route_id": prov,
                    "route_name": str(route.get("route_name") or ""),
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


def _fetch_mtr_bus_eta_map(route_name: str) -> dict[str, list[str]]:
    """One POST returns all stops for an MTR Bus route."""
    url = params.get("api", {}).get(
        "mtr_bus_schedule_url",
        "https://rt.data.gov.hk/v1/transport/mtr/bus/getSchedule",
    )
    try:
        r = requests.post(
            url,
            json={"language": "en", "routeName": str(route_name).strip()},
            timeout=20,
            headers={"User-Agent": "YuuTraffic/1.0", "Accept": "application/json"},
        )
        if r.status_code != HTTP_OK:
            return {}
        data = r.json()
        out: dict[str, list[str]] = {}
        for bs in data.get("busStop") or []:
            if not isinstance(bs, dict):
                continue
            sid = str(bs.get("busStopId") or "")
            if not sid:
                continue
            etas = []
            for bus in (bs.get("bus") or [])[:4]:
                if not isinstance(bus, dict):
                    continue
                t = bus.get("arrivalTimeText") or bus.get("departureTimeText")
                if t is None:
                    continue
                ts = str(t).strip()
                if ts and ts not in ("", "—"):
                    etas.append(ts)
            if etas:
                out[sid] = etas[:3]
        return out
    except Exception as e:
        logger.debug("MTR Bus ETA %s: %s", route_name, e)
        return {}


def fetch_etas_for_stops(
    route_id: str,
    stop_ids: list[str],
    service_type: int = 1,
    max_stops: int = 20,
    minutes_format: bool = True,
    company: str = "",
    provider_route_id: str | None = None,
    route_direction: int = 1,
    stop_sequences: list[int] | None = None,
) -> dict[str, list[str]]:
    """
    Fetch real-time ETAs: KMB, Citybus, green minibus (etagmb), or MTR Bus (single schedule POST).
    """
    import time as _time

    comp_u = str(company or "").upper()
    if "MTR" in comp_u and "BUS" in comp_u:
        return _fetch_mtr_bus_eta_map(provider_route_id or route_id)

    if "GMB" in comp_u:
        gmb_base = (
            params.get("api", {})
            .get("gmb_base_url", "https://data.etagmb.gov.hk")
            .rstrip("/")
        )
        prov = str(provider_route_id or "").strip()
        if not prov:
            return {}
        result: dict[str, list[str]] = {}
        stops = stop_ids[:max_stops]
        seqs = stop_sequences or []
        if len(seqs) < len(stops):
            seqs = list(seqs) + list(range(len(seqs) + 1, len(stops) + 1))
        for i, stop_id in enumerate(stops):
            seq = int(seqs[i]) if i < len(seqs) else i + 1
            try:
                url = f"{gmb_base}/eta/route-stop/{prov}/{int(route_direction)}/{seq}"
                r = requests.get(
                    url,
                    timeout=10,
                    headers={
                        "User-Agent": "YuuTraffic/1.0",
                        "Accept": "application/json",
                    },
                )
                if r.status_code != HTTP_OK:
                    continue
                payload = r.json()
                block = payload.get("data") or {}
                if block.get("enabled") is False:
                    continue
                entries = block.get("eta") or []
                if not isinstance(entries, list):
                    entries = []
                etas = []
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    ts = e.get("timestamp")
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
                                etas.append(
                                    str(ts)[:5] if len(str(ts)) >= 5 else str(ts)
                                )
                    elif e.get("diff") is not None:
                        etas.append(f"{e.get('diff')} min")
                if etas:
                    result[stop_id] = etas[:3]
            except Exception as e:
                logger.debug("GMB ETA %s seq %s: %s", stop_id, seq, e)
            if i < len(stops) - 1:
                _time.sleep(0.08)
        return result

    is_ctb = comp_u.startswith("CTB")
    if is_ctb:
        base_url = params.get("api", {}).get(
            "citybus_base_url", "https://rt.data.gov.hk/v2/transport/citybus"
        )
        base_url = f"{base_url}/eta/ctb"
    else:
        base_url = params.get("api", {}).get(
            "kmb_base_url", "https://data.etabus.gov.hk/v1/transport/kmb"
        )
    result: dict[str, list[str]] = {}
    stops = stop_ids[:max_stops]
    for i, stop_id in enumerate(stops):
        try:
            if is_ctb:
                url = f"{base_url}/{stop_id}/{route_id}"
            else:
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
