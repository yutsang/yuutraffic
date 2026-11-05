"""
MTR-family API helpers for railway and Light Rail data.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


LINE_NAMES: dict[str, tuple[str, str]] = {
    "AEL": ("Airport Express", "機場快綫"),
    "DRL": ("Disneyland Resort Line", "迪士尼綫"),
    "EAL": ("East Rail Line", "東鐵綫"),
    "ISL": ("Island Line", "港島綫"),
    "KTL": ("Kwun Tong Line", "觀塘綫"),
    "SIL": ("South Island Line", "南港島綫"),
    "TCL": ("Tung Chung Line", "東涌綫"),
    "TKL": ("Tseung Kwan O Line", "將軍澳綫"),
    "TML": ("Tuen Ma Line", "屯馬綫"),
    "TWL": ("Tsuen Wan Line", "荃灣綫"),
}


LIGHT_RAIL_STATION_EXAMPLES: dict[str, str] = {
    "1": "Tuen Mun Ferry Pier",
    "100": "Siu Hong",
    "295": "Tuen Mun",
    "430": "Tin Shui Wai",
    "520": "Tin Sau",
}


def parse_light_rail_routes_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse the official Light Rail routes/stops CSV into normalized rows."""
    text = (csv_text or "").lstrip("\ufeff")
    if not text.strip():
        return []
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        route_no = str(row.get("Line Code", "") or "").strip().upper()
        stop_code = str(row.get("Stop Code", "") or "").strip().upper()
        if not route_no or not stop_code:
            continue
        try:
            sequence = int(float(row.get("Sequence", "") or 0))
        except (TypeError, ValueError):
            sequence = 0
        try:
            stop_id = str(int(float(row.get("Stop ID", "") or 0)))
        except (TypeError, ValueError):
            stop_id = str(row.get("Stop ID", "") or "").strip()
        rows.append(
            {
                "route_no": route_no,
                "direction": str(row.get("Direction", "") or "").strip().upper(),
                "stop_code": stop_code,
                "stop_id": stop_id,
                "name_tc": str(row.get("Chinese Name", "") or "").strip(),
                "name_en": str(row.get("English Name", "") or "").strip() or stop_code,
                "sequence": sequence,
            }
        )
    return rows


def parse_rail_lines_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse the official MTR lines/stations CSV into normalized rows."""
    text = (csv_text or "").lstrip("\ufeff")
    if not text.strip():
        return []
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        line_code = str(row.get("Line Code", "") or "").strip().upper()
        station_code = str(row.get("Station Code", "") or "").strip().upper()
        if not line_code or not station_code:
            continue
        try:
            station_id = int(float(row.get("Station ID", "") or 0))
        except (TypeError, ValueError):
            station_id = 0
        try:
            sequence = int(float(row.get("Sequence", "") or 0))
        except (TypeError, ValueError):
            sequence = 0
        rows.append(
            {
                "line_code": line_code,
                "direction": str(row.get("Direction", "") or "").strip().upper(),
                "station_code": station_code,
                "station_id": station_id,
                "name_tc": str(row.get("Chinese Name", "") or "").strip(),
                "name_en": str(row.get("English Name", "") or "").strip()
                or station_code,
                "sequence": sequence,
            }
        )
    return rows


def _get_text(url: str, *, timeout: float) -> str:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content.decode("utf-8-sig", errors="replace")


def _get_json(url: str, *, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def load_rail_lines_and_stations(
    lines_url: str, *, timeout: float = 20.0
) -> list[dict[str, Any]]:
    """Fetch and parse the official railway lines/stations CSV."""
    try:
        return parse_rail_lines_csv(_get_text(lines_url, timeout=timeout))
    except Exception as exc:  # pragma: no cover - network errors depend on runtime
        logger.warning("Failed to load MTR lines/stations CSV: %s", exc)
        return []


def load_light_rail_routes_and_stops(
    routes_url: str, *, timeout: float = 20.0
) -> list[dict[str, Any]]:
    """Fetch and parse the official Light Rail routes/stops CSV."""
    try:
        return parse_light_rail_routes_csv(_get_text(routes_url, timeout=timeout))
    except Exception as exc:  # pragma: no cover - network errors depend on runtime
        logger.warning("Failed to load Light Rail routes/stops CSV: %s", exc)
        return []


def fetch_rail_eta(
    line_code: str,
    station_code: str,
    *,
    base_url: str,
    timeout: float = 12.0,
    lang: str = "EN",
) -> dict[str, list[dict[str, str]]]:
    """Fetch live railway ETA data keyed by direction (`UP`, `DOWN`)."""
    line = (line_code or "").strip().upper()
    station = (station_code or "").strip().upper()
    if not line or not station:
        return {}
    try:
        payload = _get_json(
            base_url,
            params={"line": line, "sta": station, "lang": lang},
            timeout=timeout,
        )
    except Exception as exc:  # pragma: no cover - network errors depend on runtime
        logger.warning("Failed to fetch railway ETA for %s-%s: %s", line, station, exc)
        return {}
    data = payload.get("data", {}) or {}
    block = data.get(f"{line}-{station}", {}) or {}
    out: dict[str, list[dict[str, str]]] = {}
    for direction in ("UP", "DOWN"):
        trains = block.get(direction, []) or []
        parsed: list[dict[str, str]] = []
        for train in trains:
            if str(train.get("valid", "Y")).upper() != "Y":
                continue
            parsed.append(
                {
                    "dest": str(train.get("dest", "") or "").strip().upper(),
                    "platform": str(train.get("plat", "") or "").strip(),
                    "minutes": str(train.get("ttnt", "") or "").strip(),
                    "time": str(train.get("time", "") or "").strip(),
                }
            )
        if parsed:
            out[direction] = parsed
    return out


def trains_for_planned_rail_direction(
    eta: dict[str, list[dict[str, str]]],
    terminal_station_code: str,
) -> list[dict[str, str]]:
    """
    Return trains for the planned direction of travel only.

    The schedule API splits arrivals into UP/DOWN; for a known journey we match the
    line terminal (train destination) and return that side's list. If the terminal
    is unknown or unmatched, return the first non-empty UP/DOWN list.
    """
    pref = (terminal_station_code or "").strip().upper()
    if pref:
        for direction in ("UP", "DOWN"):
            trains = eta.get(direction) or []
            matched = [
                t for t in trains if (t.get("dest") or "").strip().upper() == pref
            ]
            if matched:
                return matched
    for direction in ("UP", "DOWN"):
        trains = eta.get(direction) or []
        if trains:
            return trains
    return []


def fetch_light_rail_eta(
    station_id: str,
    *,
    base_url: str,
    timeout: float = 12.0,
) -> list[dict[str, Any]]:
    """Fetch live Light Rail ETA rows grouped by platform."""
    sid = str(station_id or "").strip()
    if not sid:
        return []
    try:
        payload = _get_json(base_url, params={"station_id": sid}, timeout=timeout)
    except Exception as exc:  # pragma: no cover - network errors depend on runtime
        logger.warning("Failed to fetch Light Rail ETA for %s: %s", sid, exc)
        return []
    platforms = payload.get("platform_list", []) or []
    return platforms if isinstance(platforms, list) else []
