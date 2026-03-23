"""
MTR routing, railway ETA, Light Rail ETA, and station layout summary.
"""

from __future__ import annotations

import html
import os
import sys

_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)
_src = os.path.join(_root, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import folium
import streamlit as st
from streamlit_folium import st_folium

from yuutraffic.config import load_config
from yuutraffic.lrt_routing import (
    find_light_rail_route,
)
from yuutraffic.lrt_routing import stop_options as light_rail_stop_options
from yuutraffic.mtr_client import (
    LIGHT_RAIL_STATION_EXAMPLES,
    fetch_light_rail_eta,
    fetch_rail_eta,
    load_light_rail_routes_and_stops,
    load_rail_lines_and_stations,
    trains_for_planned_rail_direction,
)
from yuutraffic.mtr_layout import (
    fetch_station_layout_data,
    fetch_station_venues,
    match_station_venue,
    parse_station_venues,
)
from yuutraffic.mtr_routing import (
    LINE_COLORS,
    estimate_mtr_journey_minutes,
    find_route,
    line_display,
    station_options,
)

st.set_page_config(page_title="MTR Routing & ETA", page_icon="🚇", layout="wide")


_LRT_COLOR = "#b45309"


def _line_badge(line_code: str) -> str:
    en, tc = line_display(line_code)
    color = LINE_COLORS.get(line_code, "#374151")
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;font-weight:700;'
        f'padding:4px 10px;border-radius:999px;font-size:0.85rem;">'
        f"{html.escape(line_code)}"
        f'</span><span style="font-weight:600;">{html.escape(en)} · {html.escape(tc)}</span>'
    )


def _light_rail_badge(route_no: str) -> str:
    return (
        f'<span style="display:inline-block;background:{_LRT_COLOR};color:#fff;font-weight:700;'
        f'padding:4px 10px;border-radius:999px;font-size:0.85rem;">{html.escape(route_no)}</span>'
        f'<span style="font-weight:600;">Light Rail · 輕鐵</span>'
    )


def _walk_badge() -> str:
    return (
        '<span style="display:inline-block;background:#4b5563;color:#fff;font-weight:700;'
        'padding:4px 10px;border-radius:999px;font-size:0.85rem;">Walk</span>'
    )


def _station_label(meta: dict[str, str], code_key: str = "code") -> str:
    tc = meta.get("name_tc", "")
    code = meta.get(code_key) or meta.get("id") or meta.get("code") or ""
    if tc:
        return f"{meta['name_en']} / {tc} [{code}]"
    return f"{meta['name_en']} [{code}]"


def _route_summary_html(total_stops: int, interchanges: int, badges_html: str) -> str:
    return (
        f'<div style="padding:0.15rem 0 0.35rem 0;">'
        f'<div style="display:flex;gap:0.6rem;flex-wrap:wrap;margin-bottom:0.45rem;">'
        f'<span style="display:inline-block;background:#111827;color:#fff;font-weight:700;'
        f'padding:5px 12px;border-radius:999px;">{total_stops} stops</span>'
        f'<span style="display:inline-block;background:#1f6feb;color:#fff;font-weight:700;'
        f'padding:5px 12px;border-radius:999px;">{interchanges} interchange(s)</span>'
        f"</div>"
        f'<div style="display:flex;gap:0.45rem 0.6rem;align-items:center;flex-wrap:wrap;">'
        f"{badges_html}"
        f"</div></div>"
    )


def _render_route_summary(route: dict, stations: dict[str, dict]) -> None:
    seg_parts: list[str] = []
    for segment in route["segments"]:
        if segment.kind == "walk":
            seg_parts.append(_walk_badge())
        else:
            seg_parts.append(_line_badge(segment.line_code))
    st.markdown(
        _route_summary_html(
            route["total_stops"], route["interchanges"], "".join(seg_parts)
        ),
        unsafe_allow_html=True,
    )


def _trip_planner_time_pill(text: str, *, bg: str = "#475569") -> str:
    """Match Trip Planner step time pills (2_Trip_Planner _step_header)."""
    return (
        f'<span style="display:inline-block;background:{bg};color:#fff;font-weight:600;'
        f'padding:5px 13px;border-radius:999px;font-size:0.88rem;">{html.escape(text)}</span>'
    )


def _est_minute_pill(minutes: float) -> str:
    return _trip_planner_time_pill(f"~{minutes:g} min", bg="#475569")


def _live_eta_pill(label: str) -> str:
    """Live arrival minutes — same pill geometry as Trip Planner."""
    return _trip_planner_time_pill(label, bg="#64748b")


def _platform_tag_html(plat: str) -> str:
    """Platform in a clear rounded-rectangle frame (high contrast vs page background)."""
    p = (plat or "").strip() or "—"
    return (
        f'<span style="display:inline-block;box-sizing:border-box;background:#fff;'
        f"color:#0f172a;border:2px solid #334155;font-weight:700;font-size:0.82rem;"
        f"padding:4px 12px;border-radius:10px;line-height:1.25;"
        f'box-shadow:0 1px 2px rgba(15,23,42,0.08);letter-spacing:0.02em;">'
        f"Plat {html.escape(str(p))}</span>"
    )


def _light_rail_route_badge(route_id: str) -> str:
    """Trip Planner–style route chip (cf. _route_badge_html), Light Rail colours."""
    badge = html.escape((route_id or "").strip() or "—")
    return (
        '<span style="display:inline-block;background:linear-gradient(135deg,#b45309,#d97706);'
        f'color:#fff;font-weight:600;padding:2px 9px;border-radius:7px;font-size:0.85rem;">{badge}</span>'
    )


def _rail_boarding_second_line_html(
    trains: list[dict[str, str]],
    *,
    line_code: str,
    stations: dict[str, dict],
    est_minutes: float | None,
) -> str:
    """
    One tight line under the route badge: Plat … live ETAs … ~estimate min.
    Destination is on the line above — no duplicate header or terminal badge here.
    """
    line_color = LINE_COLORS.get(line_code, "#374151")
    est_wrap = ""
    if est_minutes is not None:
        est_wrap = (
            '<span style="margin-left:auto;flex-shrink:0;display:inline-flex;align-items:center;">'
            f"{_est_minute_pill(est_minutes)}</span>"
        )

    if not trains:
        return (
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:0.5rem;'
            f'flex-wrap:wrap;margin-top:0.28rem;line-height:1.35;width:100%;box-sizing:border-box;">'
            '<span style="color:#94a3b8;font-size:0.82rem;">No live ETA</span>'
            f"{est_wrap}</div>"
        )

    sliced = trains[:6]
    d0 = (sliced[0].get("dest") or "").strip().upper()
    p0 = (sliced[0].get("platform") or "").strip()
    same_dest_plat = len(sliced) > 1 and all(
        (t.get("dest") or "").strip().upper() == d0
        and (t.get("platform") or "").strip() == p0
        for t in sliced
    )

    if same_dest_plat or len(sliced) == 1:
        eta_chips = []
        for t in sliced:
            mins_raw = (t.get("minutes") or "").strip()
            label = f"{mins_raw} min" if mins_raw else "—"
            eta_chips.append(_live_eta_pill(label))
        plat_show = p0 if p0 else "—"
        return (
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:0.5rem;'
            f'flex-wrap:wrap;margin-top:0.28rem;line-height:1.35;width:100%;box-sizing:border-box;">'
            f'<div style="display:flex;align-items:center;gap:0.45rem;flex-wrap:wrap;flex:1;min-width:0;">'
            f"{_platform_tag_html(plat_show)}"
            f'<span style="display:inline-flex;align-items:center;gap:0.3rem;flex-wrap:wrap;">'
            f'{"".join(eta_chips)}</span>'
            f"</div>"
            f"{est_wrap}</div>"
        )

    rows_html: list[str] = []
    for t in sliced[:4]:
        dest_code = (t.get("dest") or "").strip().upper()
        dest_name = stations.get(dest_code, {}).get("name_en", dest_code or "—")
        plat = (t.get("platform") or "").strip() or "—"
        mins_raw = (t.get("minutes") or "").strip()
        mins_display = f"{mins_raw} min" if mins_raw else "—"
        rows_html.append(
            '<div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;'
            'margin:0.1rem 0;line-height:1.35;">'
            f'<span style="display:inline-block;background:{line_color};color:#fff;font-weight:600;'
            f'padding:4px 10px;border-radius:999px;font-size:0.82rem;">'
            f"{html.escape(dest_name)}</span>"
            f"{_platform_tag_html(plat)}"
            f'<span style="display:inline-block;background:#64748b;color:#fff;font-weight:600;'
            f'padding:5px 13px;border-radius:999px;font-size:0.88rem;">{html.escape(mins_display)}</span>'
            "</div>"
        )
    return (
        f'<div style="margin-top:0.28rem;">{"".join(rows_html)}'
        f'<div style="display:flex;justify-content:flex-end;width:100%;margin-top:0.25rem;">'
        f"{est_wrap}</div></div>"
    )


def _render_route_steps(
    route: dict,
    stations: dict[str, dict],
    *,
    is_light_rail: bool = False,
    segment_minutes: list[float] | None = None,
    rail_eta_trains: list[list[dict[str, str]] | None] | None = None,
) -> None:
    st.markdown("#### Journey")
    for idx, segment in enumerate(route["segments"], start=1):
        if is_light_rail:
            badge = _light_rail_badge(segment.route_no)
            start = stations[segment.from_stop]["name_en"]
            end = stations[segment.to_stop]["name_en"]
            stop_names = [stations[code]["name_en"] for code in segment.stops]
        elif segment.kind == "walk":
            badge = _walk_badge()
            start = stations.get(segment.from_station, {}).get(
                "name_en", segment.from_station
            )
            end = stations.get(segment.to_station, {}).get(
                "name_en", segment.to_station
            )
            stop_names = []
        else:
            badge = _line_badge(segment.line_code)
            start = stations[segment.from_station]["name_en"]
            end = stations[segment.to_station]["name_en"]
            stop_names = [stations[code]["name_en"] for code in segment.stations]
        mins = None
        if segment_minutes is not None and idx <= len(segment_minutes):
            mins = segment_minutes[idx - 1]
        time_html = ""
        if mins is not None:
            time_html = (
                f'<span style="display:inline-block;background:#475569;color:#fff;font-weight:700;'
                f'padding:4px 10px;border-radius:999px;font-size:0.82rem;margin-left:auto;">~{mins:g} min</span>'
            )
        is_rail_leg = not is_light_rail and segment.kind == "rail"
        second_line_rail = ""
        if is_rail_leg and rail_eta_trains is not None and idx <= len(rail_eta_trains):
            leg_trains = rail_eta_trains[idx - 1]
            if leg_trains is not None:
                second_line_rail = _rail_boarding_second_line_html(
                    leg_trains,
                    line_code=segment.line_code,
                    stations=stations,
                    est_minutes=mins,
                )

        if is_rail_leg:
            if not second_line_rail and mins is not None:
                second_line_rail = (
                    f'<div style="display:flex;align-items:center;gap:0.45rem;flex-wrap:wrap;'
                    f'margin-top:0.28rem;">{_est_minute_pill(mins)}</div>'
                )
            st.markdown(
                f'<div style="border:1px solid rgba(128,128,128,0.22);border-radius:10px;padding:0.55rem 0.7rem;'
                f'margin:0.35rem 0;">'
                f'<div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">'
                f'<span style="display:inline-flex;align-items:center;justify-content:center;'
                f"width:28px;height:28px;border-radius:999px;background:#111827;color:#fff;"
                f'font-weight:700;">{idx}</span>{badge}'
                f'<span style="font-weight:600;">{html.escape(end)}</span>'
                f"</div>"
                f"{second_line_rail}"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="border:1px solid rgba(128,128,128,0.22);border-radius:10px;padding:0.7rem 0.85rem;'
                f'margin:0.45rem 0;">'
                f'<div style="display:flex;align-items:center;gap:0.55rem;flex-wrap:wrap;justify-content:space-between;">'
                f'<div style="display:flex;align-items:center;gap:0.55rem;flex-wrap:wrap;">'
                f'<span style="display:inline-flex;align-items:center;justify-content:center;'
                f"width:28px;height:28px;border-radius:999px;background:#111827;color:#fff;"
                f'font-weight:700;">{idx}</span>{badge}'
                f"</div>"
                f"{time_html}"
                f"</div>"
                f'<div style="margin-top:0.45rem;font-weight:600;">{html.escape(start)} &rarr; {html.escape(end)}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )
        if stop_names:
            st.caption(" -> ".join(stop_names))


def _render_light_rail_eta_trip_planner(
    rows: list[dict[str, str]], *, title: str
) -> None:
    """Light Rail live board — same visual language as Trip Planner (route badge, time pill right)."""
    st.markdown(f"#### {title}")
    if not rows:
        st.caption("No live ETA returned right now.")
        return
    lines: list[str] = []
    for row in rows[:8]:
        route = str(row.get("route", row.get("direction", "")) or "").strip()
        dest = str(row.get("dest", "") or "").strip()
        plat = str(row.get("platform", "—") or "—").strip()
        eta = str(row.get("eta", "—") or "—").strip()
        lines.append(
            f'<div style="display:flex;align-items:center;gap:10px;margin:0 0 8px 0;flex-wrap:wrap;">'
            f"{_light_rail_route_badge(route)}"
            f'<span style="font-weight:600;font-size:0.95rem;line-height:1.45;">{html.escape(dest or "—")}</span>'
            f"{_platform_tag_html(plat)}"
            '<span style="margin-left:auto;flex-shrink:0;display:inline-flex;align-items:center;">'
            f"{_trip_planner_time_pill(eta, bg='#64748b')}</span>"
            f"</div>"
        )
    st.markdown("".join(lines), unsafe_allow_html=True)


def _light_rail_eta_rows(platforms: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for platform in platforms:
        platform_id = str(platform.get("platform_id", "?"))
        for item in (platform.get("route_list", []) or [])[:4]:
            rows.append(
                {
                    "route": str(item.get("route_no", "") or "").strip(),
                    "dest": str(item.get("dest_en", "") or "").strip(),
                    "platform": platform_id,
                    "eta": str(item.get("time_en", "") or "").strip(),
                }
            )
    return rows[:8]


def _bounds_from_points(
    points: list[tuple[float, float]],
) -> tuple[list[float], list[float]] | None:
    if not points:
        return None
    lats = [pt[0] for pt in points]
    lngs = [pt[1] for pt in points]
    return [min(lats), min(lngs)], [max(lats), max(lngs)]


def _amenity_color(category: str) -> str:
    cat = (category or "").lower()
    if "elevator" in cat:
        return "#2563eb"
    if "escalator" in cat:
        return "#16a34a"
    if "stairs" in cat:
        return "#9333ea"
    return "#6b7280"


def _layout_map(layout: dict, level_id: str):
    level = next(
        (
            lvl
            for lvl in layout.get("levels_meta", [])
            if lvl.get("level_id") == level_id
        ),
        None,
    )
    if not level:
        return None
    center = level.get("center")
    if not center:
        return None
    m = folium.Map(
        location=list(center),
        zoom_start=19,
        tiles="CartoDB positron",
        control_scale=False,
    )
    level_points = [(pt[1], pt[0]) for pt in level.get("points", [])]
    if len(level_points) >= 3:
        folium.Polygon(
            locations=level_points,
            color="#1d4ed8",
            weight=2,
            fill=True,
            fill_opacity=0.08,
        ).add_to(m)
    all_points: list[tuple[float, float]] = []
    for unit in layout.get("units_meta", []):
        if unit.get("level_id") != level_id:
            continue
        pts = [(pt[1], pt[0]) for pt in unit.get("points", [])]
        if len(pts) >= 3:
            folium.Polygon(
                locations=pts,
                color="#9ca3af",
                weight=1,
                fill=True,
                fill_opacity=0.06,
            ).add_to(m)
            all_points.extend(pts)
    for opening in layout.get("openings_meta", []):
        if opening.get("level_id") != level_id:
            continue
        pts = [(pt[1], pt[0]) for pt in opening.get("points", [])]
        if len(pts) >= 2:
            folium.PolyLine(
                pts, color="#f97316", weight=4, tooltip=opening.get("label", "Opening")
            ).add_to(m)
            all_points.extend(pts)
    for amenity in layout.get("amenities_meta", []):
        if amenity.get("level_id") != level_id or not amenity.get("point"):
            continue
        lat, lng = amenity["point"]
        folium.CircleMarker(
            location=[lat, lng],
            radius=5,
            color=_amenity_color(str(amenity.get("category", ""))),
            fill=True,
            fill_opacity=0.95,
            tooltip=str(amenity.get("name_en") or amenity.get("category") or "Amenity"),
        ).add_to(m)
        all_points.append((lat, lng))
    bounds = _bounds_from_points(all_points or level_points)
    if bounds:
        m.fit_bounds(bounds, padding=(18, 18))
    return m


def _render_layout_inspector(
    station_code: str,
    stations: dict[str, dict],
    venues: list[dict],
    layout_url: str,
    timeout: float,
    *,
    key_prefix: str,
) -> None:
    station_name = stations.get(station_code, {}).get("name_en", station_code)
    venue = match_station_venue(station_name, venues)
    if not venue:
        st.caption("No station layout venue matched this station.")
        return
    layout = _load_layout_data(layout_url, venue["venue_id"], timeout)
    if not layout:
        st.caption("Station layout data is unavailable right now.")
        return
    levels = layout.get("levels_meta", [])
    if not levels:
        st.caption("No indoor level data returned for this station.")
        return
    st.markdown(f"#### Station Layout · {station_name}")
    level_ids = [lvl["level_id"] for lvl in levels]
    level_map = {
        lvl["level_id"]: (
            f"{lvl.get('short_name_en') or ''} · {lvl.get('name_en') or lvl['level_id']}"
        ).strip(" ·")
        for lvl in levels
    }
    picked_level = st.selectbox(
        "Floor",
        level_ids,
        format_func=lambda lid: level_map[lid],
        key=f"{key_prefix}_layout_level",
    )
    map_obj = _layout_map(layout, picked_level)
    current_level_name = level_map.get(picked_level, picked_level)
    nearest = [
        row
        for row in layout.get("nearest_openings", [])
        if row.get("level_name_en")
        == next(
            (lvl.get("name_en") for lvl in levels if lvl["level_id"] == picked_level),
            "",
        )
    ]
    col_map, col_side = st.columns([2.3, 1], gap="medium")
    with col_map:
        if map_obj is not None:
            st_folium(
                map_obj,
                height=380,
                use_container_width=True,
                returned_objects=[],
                key=f"{key_prefix}_layout_map_{picked_level}",
            )
        else:
            st.caption("Unable to render the selected level map.")
    with col_side:
        st.markdown(f"**{current_level_name}**")
        st.caption(
            "Orange lines are openings/exits. Markers show lifts, escalators, stairs and other amenities on this floor."
        )
        if nearest:
            st.markdown("**Closest openings**")
            for row in nearest[:5]:
                st.caption(
                    f"{row['opening_label']} -> {row['amenity_name']} ({row['distance_hint']}m)"
                )
        else:
            st.caption("No opening-to-amenity guidance on this floor.")
        amenity_counts = layout.get("amenity_counts", {})
        if amenity_counts:
            st.caption(
                "Amenities: "
                + ", ".join(
                    f"{name} ({count})"
                    for name, count in list(amenity_counts.items())[:6]
                )
            )


def _render_light_rail_route_summary(route: dict) -> None:
    badges = "".join(
        _light_rail_badge(segment.route_no) for segment in route["segments"]
    )
    st.markdown(
        _route_summary_html(route["total_stops"], route["interchanges"], badges),
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=3600)
def _load_lines(lines_url: str, timeout: float) -> list[dict]:
    return load_rail_lines_and_stations(lines_url, timeout=timeout)


@st.cache_data(ttl=3600)
def _load_light_rail_rows(routes_url: str, timeout: float) -> list[dict]:
    return load_light_rail_routes_and_stops(routes_url, timeout=timeout)


@st.cache_data(ttl=3600)
def _load_venues(layout_url: str, timeout: float) -> list[dict]:
    return parse_station_venues(fetch_station_venues(layout_url, timeout=timeout))


@st.cache_data(ttl=10)
def _load_rail_eta(
    line_code: str, station_code: str, rail_eta_url: str, timeout: float
) -> dict:
    return fetch_rail_eta(
        line_code, station_code, base_url=rail_eta_url, timeout=timeout
    )


@st.cache_data(ttl=10)
def _load_light_rail_eta(
    station_id: str, light_rail_eta_url: str, timeout: float
) -> list[dict]:
    return fetch_light_rail_eta(
        station_id, base_url=light_rail_eta_url, timeout=timeout
    )


@st.cache_data(ttl=21600)
def _load_layout_data(layout_url: str, venue_id: str, timeout: float) -> dict:
    return fetch_station_layout_data(layout_url, venue_id, timeout=timeout)


def main() -> None:
    st.title("🚇 MTR Routing & ETA")
    st.caption(
        "Plan MTR railway journeys: live ETA at each rail boarding station (direction matches your route), "
        "heuristic segment and total times, station layout map, and Light Rail routing with live boards."
    )

    params = load_config()
    api = params.get("api", {}) or {}
    mtr_cfg = params.get("mtr", {}) or {}
    timeout = float(api.get("timeout", 20) or 20)
    lines_url = api.get(
        "mtr_lines_stations_url",
        "https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv",
    )
    rail_eta_url = api.get(
        "mtr_next_train_url", "https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php"
    )
    light_rail_eta_url = api.get(
        "mtr_light_rail_schedule_url",
        "https://rt.data.gov.hk/v1/transport/mtr/lrt/getSchedule",
    )
    light_rail_routes_url = api.get(
        "mtr_light_rail_routes_stops_url",
        "https://opendata.mtr.com.hk/data/light_rail_routes_and_stops.csv",
    )
    layout_url = api.get(
        "mtr_indoor_map_base_url", "https://mapapi.hkmapservice.gov.hk/ogc/wfs/indoor"
    )
    transfer_penalty = float(mtr_cfg.get("routing_transfer_penalty", 4.0) or 4.0)
    light_rail_transfer_penalty = float(
        mtr_cfg.get("light_rail_transfer_penalty", 3.0) or 3.0
    )

    rows = _load_lines(lines_url, timeout)
    if not rows:
        st.error("Unable to load MTR line metadata.")
        return
    venues = _load_venues(layout_url, timeout)
    light_rail_rows = _load_light_rail_rows(light_rail_routes_url, timeout)
    options = station_options(rows)
    code_to_meta = {item["code"]: item for item in options}
    light_rail_options = light_rail_stop_options(light_rail_rows)
    light_rail_meta = {item["id"]: item for item in light_rail_options}

    st.markdown("### MTR Railway")
    left, right = st.columns(2)
    with left:
        origin_code = st.selectbox(
            "Origin station",
            [opt["code"] for opt in options],
            format_func=lambda code: _station_label(code_to_meta[code]),
            key="mtr_origin",
        )
    with right:
        destination_choices = [
            opt["code"] for opt in options if opt["code"] != origin_code
        ]
        destination_code = st.selectbox(
            "Destination station",
            destination_choices,
            format_func=lambda code: _station_label(code_to_meta[code]),
            key="mtr_destination",
        )

    if st.button("Plan MTR route", type="primary", use_container_width=True):
        st.session_state["mtr_route_request"] = {
            "origin": origin_code,
            "dest": destination_code,
        }

    request = st.session_state.get("mtr_route_request")
    if request:
        route = find_route(
            rows,
            request.get("origin", ""),
            request.get("dest", ""),
            transfer_penalty=transfer_penalty,
        )
        if route is None:
            st.warning("No railway path found for that station pair.")
        else:
            stations = route["stations"]
            origin_name = stations[request["origin"]]["name_en"]
            dest_name = stations[request["dest"]]["name_en"]
            with st.expander(
                f"{origin_name} -> {dest_name} · {route['total_stops']} stops · {route['interchanges']} interchange(s)",
                expanded=True,
            ):
                _render_route_summary(route, stations)
                breakdown, total_mins = estimate_mtr_journey_minutes(
                    route["segments"],
                    minutes_per_rail_stop=float(
                        mtr_cfg.get("rail_minutes_per_stop", 2.5) or 2.5
                    ),
                    walk_leg_minutes=float(mtr_cfg.get("walk_leg_minutes", 5.0) or 5.0),
                    interchange_minutes=float(
                        mtr_cfg.get("interchange_minutes", 3.0) or 3.0
                    ),
                )
                segment_minutes = [m for _, _, m in breakdown]
                st.markdown(
                    f'<div style="margin:0.35rem 0 0.65rem 0;padding:0.65rem 0.9rem;border-radius:10px;'
                    f'background:linear-gradient(90deg,rgba(30,64,175,0.1),transparent);border-left:4px solid #1e40af;">'
                    f"<strong>Estimated journey time</strong> &nbsp;·&nbsp; "
                    f'<span style="font-size:1.05rem;font-weight:800;">~{total_mins:g} min total</span>'
                    f'<span style="color:#64748b;font-size:0.88rem;"> &nbsp;(heuristic; not live ETA)</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                rail_eta_trains: list[list[dict[str, str]] | None] = []
                for seg in route["segments"]:
                    if seg.kind != "rail":
                        rail_eta_trains.append(None)
                        continue
                    eta = _load_rail_eta(
                        seg.line_code, seg.from_station, rail_eta_url, timeout
                    )
                    trains = trains_for_planned_rail_direction(
                        eta, seg.terminal_code or ""
                    )
                    rail_eta_trains.append(trains[:6])
                _render_route_steps(
                    route,
                    stations,
                    segment_minutes=segment_minutes,
                    rail_eta_trains=rail_eta_trains,
                )
                layout_choice = st.selectbox(
                    "Layout station",
                    [request["origin"], request["dest"]],
                    format_func=lambda code: stations[code]["name_en"],
                    key="mtr_layout_station_choice",
                )
                _render_layout_inspector(
                    layout_choice,
                    stations,
                    venues,
                    layout_url,
                    timeout,
                    key_prefix=f"mtr_{layout_choice}",
                )

    st.markdown("---")
    st.markdown("### Light Rail")
    if not light_rail_rows:
        st.warning("Unable to load Light Rail routing data.")
        return
    lr_left, lr_right = st.columns(2)
    with lr_left:
        lr_origin = st.selectbox(
            "Origin stop",
            [opt["id"] for opt in light_rail_options],
            format_func=lambda sid: _station_label(light_rail_meta[sid], code_key="id"),
            key="lr_origin",
        )
    with lr_right:
        lr_dest_choices = [
            opt["id"] for opt in light_rail_options if opt["id"] != lr_origin
        ]
        lr_dest = st.selectbox(
            "Destination stop",
            lr_dest_choices,
            format_func=lambda sid: _station_label(light_rail_meta[sid], code_key="id"),
            key="lr_dest",
        )
    if st.button("Plan Light Rail route", type="primary", use_container_width=True):
        st.session_state["lr_route_request"] = {"origin": lr_origin, "dest": lr_dest}

    lr_request = st.session_state.get("lr_route_request")
    if lr_request:
        lr_route = find_light_rail_route(
            light_rail_rows,
            lr_request.get("origin", ""),
            lr_request.get("dest", ""),
            transfer_penalty=light_rail_transfer_penalty,
        )
        if lr_route is None:
            st.warning("No Light Rail path found for that stop pair.")
        else:
            lr_stops = lr_route["stops"]
            origin_name = lr_stops[lr_request["origin"]]["name_en"]
            dest_name = lr_stops[lr_request["dest"]]["name_en"]
            board_stop_id = (
                lr_route["segments"][0].from_stop
                if lr_route.get("segments")
                else lr_request["origin"]
            )
            platforms = _load_light_rail_eta(board_stop_id, light_rail_eta_url, timeout)
            with st.expander(
                f"{origin_name} -> {dest_name} · {lr_route['total_stops']} stops · {lr_route['interchanges']} interchange(s)",
                expanded=True,
            ):
                _render_light_rail_route_summary(lr_route)
                _render_light_rail_eta_trip_planner(
                    _light_rail_eta_rows(platforms),
                    title=f"Live Light Rail ETA · board at {lr_stops[board_stop_id]['name_en']}",
                )
                _render_route_steps(lr_route, lr_stops, is_light_rail=True)

    st.markdown("#### Quick Light Rail ETA board")
    board_col1, board_col2 = st.columns([2, 1])
    with board_col1:
        quick_station_id = st.selectbox(
            "Station board",
            [opt["id"] for opt in light_rail_options],
            index=(
                0
                if "100" not in light_rail_meta
                else [opt["id"] for opt in light_rail_options].index("100")
            ),
            format_func=lambda sid: _station_label(light_rail_meta[sid], code_key="id"),
            key="lrt_quick_station",
        )
    with board_col2:
        st.caption("Examples")
        st.caption(
            ", ".join(
                f"{name} [{sid}]" for sid, name in LIGHT_RAIL_STATION_EXAMPLES.items()
            )
        )
    quick_platforms = _load_light_rail_eta(
        quick_station_id, light_rail_eta_url, timeout
    )
    _render_light_rail_eta_trip_planner(
        _light_rail_eta_rows(quick_platforms),
        title=f"Station ETA · {light_rail_meta[quick_station_id]['name_en']}",
    )


main()
