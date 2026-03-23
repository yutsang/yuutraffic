"""
MTR Bus: getSchedule has no stop names and no coordinates. We derive readable labels
from busStopId (e.g. K12-D010), optional overrides in data/01_raw/mtr_bus_stop_overrides.json,
district hints from mtr_bus_routes_meta, and place stops along approximate route axes (linear interp).
D/U legs use the same axis reversed for the inbound direction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .mtr_bus_routes_meta import MTR_ROUTE_LINES, MTR_ROUTE_REGION

_MTR_ROUTE_LINES: dict[str, tuple[tuple[float, float], tuple[float, float]]] = dict(
    MTR_ROUTE_LINES
)

_MTR_STOP_ID_LEG = re.compile(r"-([DU])(\d+)$")


def mtr_bus_stop_leg(bus_stop_id: str) -> str | None:
    """Return 'D' (downbound) or 'U' (upbound) from MTR busStopId, or None."""
    m = _MTR_STOP_ID_LEG.search(bus_stop_id or "")
    if not m:
        return None
    return m.group(1)


_OVERRIDES_CACHE: dict[str, dict[str, Any]] | None = None


def _overrides_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "data"
        / "01_raw"
        / "mtr_bus_stop_overrides.json"
    )


def load_mtr_stop_overrides() -> dict[str, dict[str, Any]]:
    """busStopId -> {name_en, name_tc} from JSON (optional file)."""
    global _OVERRIDES_CACHE
    if _OVERRIDES_CACHE is not None:
        return _OVERRIDES_CACHE
    _OVERRIDES_CACHE = {}
    p = _overrides_path()
    if p.is_file():
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _OVERRIDES_CACHE = {
                    str(k): v for k, v in data.items() if isinstance(v, dict)
                }
        except (OSError, json.JSONDecodeError):
            pass
    return _OVERRIDES_CACHE


def mtr_stop_labels(bus_stop_id: str) -> tuple[str, str]:
    """English + Traditional Chinese labels; overrides file wins, then district hint, then synthetic id."""
    sid = (bus_stop_id or "").strip()
    if not sid:
        return "MTR Bus stop", "港鐵巴士站"
    ov = load_mtr_stop_overrides().get(sid)
    if ov:
        en = (ov.get("name_en") or "").strip()
        tc = (ov.get("name_tc") or "").strip()
        if en or tc:
            return en or sid, tc or en or sid
    m = re.match(r"^([A-Za-z0-9]+)-(.+)$", sid)
    if m:
        route, tail = m.group(1), m.group(2)
        reg = MTR_ROUTE_REGION.get(route)
        if reg:
            ren, rtc = reg
            return f"{route} · {tail} — {ren}", f"{route} · {tail} — {rtc}"
        en = f"MTR Bus {route} · {tail}"
        tc = f"港鐵巴士 {route} · {tail}"
        return en, tc
    return f"MTR Bus · {sid}", f"港鐵巴士 · {sid}"


def mtr_interpolate_lat_lng(
    route_name: str, sequence: int, total: int, leg: str | None = None
) -> tuple[float, float]:
    """Place stop `sequence` (1-based) along route axis.
    For MTR ids with -D- / -U-, pass leg='D' or 'U': U runs from the second endpoint back to the first.
    """
    r = (route_name or "").strip()
    line = _MTR_ROUTE_LINES.get(r)
    if line and total > 1:
        (lat0, lng0), (lat1, lng1) = line
        if leg == "U":
            lat0, lng0, lat1, lng1 = lat1, lng1, lat0, lng0
        t = (sequence - 1) / (total - 1)
        return lat0 + t * (lat1 - lat0), lng0 + t * (lng1 - lng0)
    if line and total == 1:
        a, b = line[0], line[1]
        return b if leg == "U" else a
    # Unknown geometry should stay unset so routing logic does not invent walking distances.
    return 0.0, 0.0


def enrich_mtr_stop_row(
    route_name: str,
    bus_stop_id: str,
    sequence: int,
    total: int,
    leg: str | None = None,
) -> tuple[str, str, float, float]:
    """Return (name_en, name_tc, lat, lng) for MTR Bus stops."""
    leg = leg or mtr_bus_stop_leg(bus_stop_id)
    en, tc = mtr_stop_labels(bus_stop_id)
    lat, lng = mtr_interpolate_lat_lng(route_name, sequence, total, leg)
    return en, tc, lat, lng
