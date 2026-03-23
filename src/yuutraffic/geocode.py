"""
Geocode free-text places via OpenStreetMap Nominatim (no API key).
Policy: https://operations.osmfoundation.org/policies/nominatim/ — send a valid User-Agent and avoid burst traffic.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_UA = "YuuTraffic/1.0 (trip planner; contact: local app)"


def nominatim_geocode(
    query: str,
    *,
    base_url: str = "https://nominatim.openstreetmap.org/search",
    user_agent: str = _DEFAULT_UA,
    timeout: float = 12.0,
    limit: int = 5,
    countrycodes: str | None = "hk",
) -> list[dict[str, Any]]:
    """
    Return Nominatim JSON hits (lat, lon, display_name, ...), newest first by relevance.
    Biases toward Hong Kong via countrycodes=hk and viewbox around HK.
    """
    q = (query or "").strip()
    if not q:
        return []
    params: dict[str, str] = {
        "q": q,
        "format": "json",
        "limit": str(limit),
        "addressdetails": "0",
        # Approximate HK bounding box (south,west,north,east) in degrees
        "viewbox": "113.80,22.15,114.45,22.58",
        "bounded": "0",
    }
    if countrycodes:
        params["countrycodes"] = countrycodes
    url = f"{base_url.rstrip('/')}?{urllib.parse.urlencode(params)}"
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Accept-Language": "en",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("Nominatim geocode failed: %s", e)
        return []


def resolve_place_lat_lng(
    query: str,
    *,
    base_url: str = "https://nominatim.openstreetmap.org/search",
    user_agent: str = _DEFAULT_UA,
    timeout: float = 12.0,
    limit: int = 5,
) -> tuple[float, float, str] | None:
    """
    Try Nominatim with HK bias, then without country filter, then with "Hong Kong" suffix.
    Returns (lat, lng, display_name) or None.
    """
    q = (query or "").strip()
    if not q:
        return None
    for cc in ("hk", None):
        hits = nominatim_geocode(
            q,
            base_url=base_url,
            user_agent=user_agent,
            timeout=timeout,
            limit=limit,
            countrycodes=cc,
        )
        first = first_lat_lng(hits)
        if first:
            return first
    if not q.lower().strip().endswith("hong kong"):
        hits = nominatim_geocode(
            f"{q} Hong Kong",
            base_url=base_url,
            user_agent=user_agent,
            timeout=timeout,
            limit=limit,
            countrycodes=None,
        )
        return first_lat_lng(hits)
    return None


def first_lat_lng(
    hits: list[dict[str, Any]],
) -> tuple[float, float, str] | None:
    """First hit as (lat, lng, display_name) or None."""
    for h in hits:
        try:
            lat = float(h.get("lat", ""))
            lng = float(h.get("lon", ""))
            name = str(h.get("display_name", "") or "")
            return lat, lng, name
        except (TypeError, ValueError):
            continue
    return None
