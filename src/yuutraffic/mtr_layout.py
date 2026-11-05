"""
Helpers for summarizing MTR indoor station layout data from the CSDI API.
"""

from __future__ import annotations

from collections import Counter
from math import hypot
from typing import Any

import requests


def normalize_station_name(name: str) -> str:
    text = (name or "").strip().lower()
    if text.endswith(" station"):
        text = text[:-8]
    if text.endswith(" railway station"):
        text = text[:-16]
    return " ".join(text.split())


def _build_url(base_url: str, feature: str, venue_id: str | None = None) -> str:
    base = base_url.rstrip("/")
    url = (
        f"{base}/{feature}?service=WFS&version=1.1.0&request=GetFeature"
        "&outputFormat=application/json"
    )
    if venue_id:
        url += f"&cql_filter=venue_id%3D%27{venue_id}%27"
    return url


def _get_json(url: str, *, timeout: float) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def fetch_station_venues(
    base_url: str, *, timeout: float = 20.0
) -> list[dict[str, Any]]:
    payload = _get_json(_build_url(base_url, "mtr_venue_polygon"), timeout=timeout)
    return payload.get("features", []) or []


def parse_station_venues(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties", {}) or {}
        name_en = str(props.get("venue_name_en", "") or "").strip()
        name_tc = str(props.get("venue_name_zh", "") or "").strip()
        venue_id = str(props.get("venue_id", "") or "").strip()
        if not venue_id or not name_en:
            continue
        out.append(
            {
                "venue_id": venue_id,
                "name_en": name_en,
                "name_tc": name_tc,
                "norm_name": normalize_station_name(name_en),
                "locality": str(props.get("address_locality", "") or "").strip(),
            }
        )
    return out


def match_station_venue(
    station_name_en: str,
    venues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    norm = normalize_station_name(station_name_en)
    for venue in venues:
        if venue.get("norm_name") == norm:
            return venue
    for venue in venues:
        if norm and norm in str(venue.get("norm_name", "")):
            return venue
    return None


def summarize_layout_payloads(
    levels_payload: dict[str, Any],
    openings_payload: dict[str, Any],
    amenities_payload: dict[str, Any],
    occupants_payload: dict[str, Any],
) -> dict[str, Any]:
    levels = levels_payload.get("features", []) or []
    openings = openings_payload.get("features", []) or []
    amenities = amenities_payload.get("features", []) or []
    occupants = occupants_payload.get("features", []) or []

    level_names: list[str] = []
    for feature in levels:
        props = feature.get("properties", {}) or {}
        name = str(props.get("level_name_en", "") or "").strip()
        if name and name not in level_names:
            level_names.append(name)

    amenity_counts = Counter()
    for feature in amenities:
        props = feature.get("properties", {}) or {}
        category = str(props.get("amenity_category", "") or "").strip()
        if category:
            amenity_counts[category] += 1

    shops: list[str] = []
    for feature in occupants:
        props = feature.get("properties", {}) or {}
        name = str(props.get("occupant_name_en", "") or "").strip()
        if name and name not in shops:
            shops.append(name)

    return {
        "levels": level_names[:8],
        "level_count": len(level_names),
        "exit_count": len(openings),
        "amenity_counts": dict(amenity_counts.most_common(8)),
        "shop_count": len(shops),
        "shops": shops[:8],
    }


def _xy_pairs(geometry: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not geometry:
        return []
    gtype = str(geometry.get("type", "") or "")
    coords = geometry.get("coordinates")
    if not coords:
        return []
    if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
        return [(float(coords[0]), float(coords[1]))]
    if gtype == "LineString":
        return [
            (float(p[0]), float(p[1]))
            for p in coords
            if isinstance(p, list) and len(p) >= 2
        ]
    if gtype == "Polygon":
        ring = coords[0] if coords and isinstance(coords[0], list) else []
        return [
            (float(p[0]), float(p[1]))
            for p in ring
            if isinstance(p, list) and len(p) >= 2
        ]
    if gtype == "MultiPolygon":
        out: list[tuple[float, float]] = []
        for poly in coords:
            if not poly or not isinstance(poly, list):
                continue
            ring = poly[0] if poly and isinstance(poly[0], list) else []
            out.extend(
                (float(p[0]), float(p[1]))
                for p in ring
                if isinstance(p, list) and len(p) >= 2
            )
        return out
    return []


def _center_from_points(
    points: list[tuple[float, float]],
) -> tuple[float, float] | None:
    if not points:
        return None
    lng = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lng


def _parse_levels(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    levels: list[dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties", {}) or {}
        level_id = str(props.get("level_id", "") or "").strip()
        if not level_id or level_id in seen:
            continue
        seen.add(level_id)
        points = _xy_pairs(feature.get("geometry"))
        levels.append(
            {
                "level_id": level_id,
                "name_en": str(props.get("level_name_en", "") or "").strip(),
                "name_tc": str(props.get("level_name_zh", "") or "").strip(),
                "short_name_en": str(
                    props.get("level_short_name_en", "") or ""
                ).strip(),
                "ordinal": int(props.get("level_ordinal", 0) or 0),
                "points": points,
                "center": _center_from_points(points),
            }
        )
    levels.sort(key=lambda item: (item["ordinal"], item["name_en"]))
    return levels


def _parse_openings(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, feature in enumerate(features, start=1):
        props = feature.get("properties", {}) or {}
        points = _xy_pairs(feature.get("geometry"))
        center = _center_from_points(points)
        label = str(props.get("opening_name", "") or "").strip()
        if not label:
            label = f"Opening {idx}"
        out.append(
            {
                "opening_id": str(props.get("opening_id", "") or "").strip(),
                "label": label,
                "category": str(props.get("opening_category", "") or "").strip(),
                "level_id": str(props.get("level_id", "") or "").strip(),
                "level_name_en": str(props.get("level_name_en", "") or "").strip(),
                "points": points,
                "center": center,
            }
        )
    return out


def _parse_amenities(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties", {}) or {}
        points = _xy_pairs(feature.get("geometry"))
        center = _center_from_points(points)
        out.append(
            {
                "amenity_id": str(props.get("amenity_id", "") or "").strip(),
                "name_en": str(props.get("amenity_name_en", "") or "").strip(),
                "category": str(props.get("amenity_category", "") or "").strip(),
                "level_id": str(props.get("level_id", "") or "").strip(),
                "level_name_en": str(props.get("level_name_en", "") or "").strip(),
                "point": center,
            }
        )
    return out


def _parse_units(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties", {}) or {}
        points = _xy_pairs(feature.get("geometry"))
        out.append(
            {
                "unit_id": str(props.get("unit_id", "") or "").strip(),
                "category": str(props.get("unit_category", "") or "").strip(),
                "name_en": str(props.get("unit_name_en", "") or "").strip(),
                "level_id": str(props.get("level_id", "") or "").strip(),
                "level_name_en": str(props.get("level_name_en", "") or "").strip(),
                "points": points,
            }
        )
    return out


def _nearest_openings(
    openings: list[dict[str, Any]],
    amenities: list[dict[str, Any]],
    categories: tuple[str, ...] = ("elevator", "escalator", "stairs"),
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for amenity in amenities:
        point = amenity.get("point")
        category = str(amenity.get("category", "") or "").strip().lower()
        if not point or category not in categories:
            continue
        best: dict[str, Any] | None = None
        best_d = float("inf")
        for opening in openings:
            if opening.get("level_id") != amenity.get("level_id"):
                continue
            center = opening.get("center")
            if not center:
                continue
            d = hypot(center[0] - point[0], center[1] - point[1])
            if d < best_d:
                best_d = d
                best = opening
        if best is not None:
            out.append(
                {
                    "amenity_name": amenity.get("name_en")
                    or amenity.get("category")
                    or "Amenity",
                    "amenity_category": amenity.get("category", ""),
                    "opening_label": best.get("label", "Opening"),
                    "level_name_en": amenity.get("level_name_en", ""),
                    "distance_hint": round(best_d * 111000, 1),
                }
            )
    uniq: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in out:
        key = (
            str(row.get("amenity_category", "")),
            str(row.get("opening_label", "")),
            str(row.get("level_name_en", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(row)
    return uniq[:8]


def build_station_layout_details(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    levels_features = payloads.get("levels", {}).get("features", []) or []
    units_features = payloads.get("units", {}).get("features", []) or []
    openings_features = payloads.get("openings", {}).get("features", []) or []
    amenities_features = payloads.get("amenities", {}).get("features", []) or []
    occupants_features = payloads.get("occupants", {}).get("features", []) or []
    summary = summarize_layout_payloads(
        payloads.get("levels", {}),
        payloads.get("openings", {}),
        payloads.get("amenities", {}),
        payloads.get("occupants", {}),
    )
    levels = _parse_levels(levels_features)
    openings = _parse_openings(openings_features)
    amenities = _parse_amenities(amenities_features)
    units = _parse_units(units_features)
    summary.update(
        {
            "levels_meta": levels,
            "openings_meta": openings,
            "amenities_meta": amenities,
            "units_meta": units,
            "nearest_openings": _nearest_openings(openings, amenities),
            "shop_count": len(
                {
                    str(
                        (f.get("properties", {}) or {}).get("occupant_name_en", "")
                        or ""
                    ).strip()
                    for f in occupants_features
                    if str(
                        (f.get("properties", {}) or {}).get("occupant_name_en", "")
                        or ""
                    ).strip()
                }
            ),
        }
    )
    return summary


def fetch_station_layout_data(
    base_url: str,
    venue_id: str,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    features = {
        "levels": "mtr_level_polygon",
        "units": "mtr_unit_polygon",
        "openings": "mtr_opening_line",
        "amenities": "mtr_amenity_point",
        "occupants": "mtr_occupant_point",
    }
    payloads = {
        key: _get_json(_build_url(base_url, feature, venue_id), timeout=timeout)
        for key, feature in features.items()
    }
    return build_station_layout_details(payloads)


def fetch_station_layout_summary(
    base_url: str,
    venue_id: str,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    return fetch_station_layout_data(base_url, venue_id, timeout=timeout)
