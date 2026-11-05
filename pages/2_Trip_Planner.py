"""
Trip planner: multi-transfer bus routing (Dijkstra on route segments) + walking catchment.
One search bar per end: stop name / ID substring match and/or OSM place → pick a result.
Run via: streamlit run app.py  → sidebar "Trip Planner"
"""

from __future__ import annotations

import html
import json
import os
import sys

_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)
_src = os.path.join(_root, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import streamlit as st

from yuutraffic.config import load_config
from yuutraffic.geocode import resolve_place_lat_lng
from yuutraffic.journey import (
    catchment_stop_ids_ordered,
    clusters_within_walk_radius,
    find_journeys,
    load_route_terminus_full,
    load_stop_clusters_for_ui,
    load_stop_coords,
    load_stop_names_bilingual,
    rank_journeys_for_trip_planner,
    toward_terminal_bilingual,
    walk_km_between_stops,
    walk_radius_km,
)

st.set_page_config(page_title="Trip Planner", page_icon="🧭", layout="wide")


@st.cache_data(ttl=300)
def _load_clusters_cached(db_path: str) -> list[dict]:
    return load_stop_clusters_for_ui(db_path, precision=4)


@st.cache_data(ttl=300)
def _load_stop_names_bi_cached(db_path: str) -> dict[str, tuple[str, str]]:
    return load_stop_names_bilingual(db_path)


@st.cache_data(ttl=300)
def _load_route_full_cached(db_path: str) -> dict[str, tuple[str, str, str, str]]:
    return load_route_terminus_full(db_path)


@st.cache_data(ttl=300)
def _load_stop_coords_cached(db_path: str) -> dict[str, tuple[float, float]]:
    return load_stop_coords(db_path)


# Straight-line distance above this → separate walk step between bus legs
_TRANSFER_WALK_KM = 0.05


def _filter_clusters(clusters: list[dict], q: str, limit: int = 100) -> list[dict]:
    if not q.strip():
        return clusters[:limit]
    s = q.lower().strip()
    out = []
    for c in clusters:
        blob = " ".join(
            [
                c.get("label", ""),
                c.get("name_primary", ""),
                " ".join(c.get("stop_ids", [])),
            ]
        ).lower()
        if s in blob or any(s in str(x).lower() for x in c.get("stop_ids", [])):
            out.append(c)
        if len(out) >= limit:
            break
    return out


def _hk_bounds(lat: float, lng: float) -> bool:
    return 22.0 <= lat <= 22.7 and 113.7 <= lng <= 114.5


def _stop_pair(stop_bi: dict[str, tuple[str, str]], sid: str) -> tuple[str, str]:
    en, tc = stop_bi.get(sid, (sid, ""))
    return (en or sid).strip() or sid, (tc or "").strip()


def _stop_id_suffix(stop_id: str | None) -> str:
    """Append API/database stop_id as a compact bracketed suffix."""
    if stop_id is None:
        return ""
    sid = str(stop_id).strip()
    if not sid:
        return ""
    e = html.escape(sid)
    return f' <span style="opacity:0.72;font-weight:600">[{e}]</span>'


# Match _step_header title weight/size for stop names; headsign stays smaller in _line_route_row.
_STOP_NAME = "font-size:1.02rem;font-weight:600;line-height:1.45"


def _biline_compact(en: str, tc: str, stop_id: str | None = None) -> None:
    """Single line: EN 中文; optional stop_id suffix from API/database."""
    en = (en or "").strip()
    tc = (tc or "").strip()
    suf = _stop_id_suffix(stop_id)
    if not en and not tc:
        st.markdown(
            f'<span style="{_STOP_NAME}">—</span>',
            unsafe_allow_html=True,
        )
        return
    if not tc or tc == en:
        st.markdown(
            f'<span style="{_STOP_NAME}">{html.escape(en or tc or "—")}{suf}</span>',
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        f'<span style="{_STOP_NAME}">{html.escape(en)} '
        f'<span style="opacity:0.82;font-weight:600">{html.escape(tc)}</span>{suf}</span>',
        unsafe_allow_html=True,
    )


def _muted(text: str) -> None:
    st.caption(text)


# Numbered step chip + time pill colors
_CLR_WALK = "#0969da"
_CLR_BUS = "#bc4c00"
_CLR_XF = "#8250df"


def _route_badge_html(op: str, route_id: str) -> str:
    badge = html.escape(f"{op} {route_id}".strip())
    return (
        '<span style="display:inline-block;background:linear-gradient(135deg,#bc4c00,#d97706);'
        f'color:#fff;font-weight:600;padding:2px 9px;border-radius:7px;font-size:0.85rem;">{badge}</span>'
    )


def _line_route_row(op: str, route_id: str, tw_en: str, tw_tc: str) -> None:
    """Line · 路線 [Op route] headsign EN 中文 (no full registered routing string)."""
    en = (tw_en or "").strip()
    tc = (tw_tc or "").strip()
    if tc and tc != en:
        head = f'{html.escape(en)} <span style="opacity:0.82">{html.escape(tc)}</span>'
    else:
        head = html.escape(en or tc or "—")
    st.markdown(
        f'<p style="margin:0.15rem 0 0.4rem 0;font-size:0.95rem;line-height:1.45;display:flex;'
        f'flex-wrap:wrap;align-items:baseline;gap:0.35rem 0.55rem;">'
        f'<span style="font-weight:600;">Line · 路線</span>'
        f"{_route_badge_html(op, route_id)}"
        f"<span>{head}</span></p>",
        unsafe_allow_html=True,
    )


def _journey_badges_html(j) -> str:
    bits: list[str] = []
    for i, leg in enumerate(j.legs):
        if i:
            bits.append('<span style="opacity:0.6;font-weight:700;">&rarr;</span>')
        bits.append(_route_badge_html(leg.company or "Bus", leg.route_id))
    return "".join(bits)


def _result_header(title: str, j, total_min: float) -> None:
    trip_kind = "Direct" if len(j.legs) == 1 else f"{len(j.legs)} legs"
    st.markdown(
        f'<div style="padding:0.15rem 0 0.55rem 0;">'
        f'<div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.35rem;">'
        f'<span style="font-weight:700;font-size:1.0rem;">{html.escape(title)}</span>'
        f'<span style="display:inline-block;background:#111827;color:#fff;font-weight:600;'
        f'padding:3px 11px;border-radius:999px;font-size:0.84rem;">~{total_min:.0f} min</span>'
        f'<span style="opacity:0.72;font-size:0.88rem;">{html.escape(trip_kind)}</span>'
        f"</div>"
        f'<div style="display:flex;align-items:center;gap:0.35rem 0.45rem;flex-wrap:wrap;">'
        f'<span style="font-weight:600;">Line · 路線</span>'
        f"{_journey_badges_html(j)}"
        f"</div></div>",
        unsafe_allow_html=True,
    )


def _step_header(
    n: int,
    title: str,
    minutes: float,
    color: str,
    *,
    chip_color: str | None = None,
) -> None:
    """Numbered step row: chip + title + time pill. Chip matches pill unless chip_color set."""
    chip = chip_color if chip_color is not None else color
    num = html.escape(str(n))
    tit = html.escape(title)
    pill = html.escape(f"~{minutes:.0f} min")
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin:0 0 10px 0;flex-wrap:wrap;">'
        f'<span style="min-width:30px;height:30px;border-radius:50%;background:{chip};color:#fff;'
        f"display:inline-flex;align-items:center;justify-content:center;font-weight:700;"
        f'font-size:0.9rem;flex-shrink:0;">{num}</span>'
        f'<span style="font-weight:600;font-size:1.02rem;">{tit}</span>'
        f'<span style="margin-left:auto;display:inline-flex;align-items:center;">'
        f'<span style="display:inline-block;background:{color};color:#fff;font-weight:600;'
        f'padding:5px 13px;border-radius:999px;font-size:0.88rem;">{pill}</span></span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _step_header_xfer_bus(n: int, total_min: float, *, chip_color: str) -> None:
    """Interchange + bus: one total time; chip and pill share chip_color (梅花間竹)."""
    num = html.escape(str(n))
    tit = html.escape("Transfer Bus · 轉乘巴士")
    pill = html.escape(f"~{total_min:.0f} min")
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin:0 0 10px 0;flex-wrap:wrap;">'
        f'<span style="min-width:30px;height:30px;border-radius:50%;background:{chip_color};color:#fff;'
        f"display:inline-flex;align-items:center;justify-content:center;font-weight:700;"
        f'font-size:0.9rem;flex-shrink:0;">{num}</span>'
        f'<span style="font-weight:600;font-size:1.02rem;">{tit}</span>'
        f'<span style="margin-left:auto;display:inline-flex;align-items:center;">'
        f'<span style="display:inline-block;background:{chip_color};color:#fff;font-weight:600;'
        f'padding:5px 13px;border-radius:999px;font-size:0.88rem;">{pill}</span></span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _label_colon_line(label: str, en: str, tc: str, stop_id: str | None = None) -> None:
    """Board · 上: EN 中文 + optional stop_id from API/database."""
    en = (en or "").strip()
    tc = (tc or "").strip()
    lab = html.escape(label)
    suf = _stop_id_suffix(stop_id)
    if not tc or tc == en:
        body = f'<span style="{_STOP_NAME}">{html.escape(en or tc or "—")}{suf}</span>'
    else:
        body = (
            f'<span style="{_STOP_NAME}">{html.escape(en)} '
            f'<span style="opacity:0.82;font-weight:600">{html.escape(tc)}</span>{suf}</span>'
        )
    st.markdown(
        f'<p style="margin:0.25rem 0;line-height:1.45;">'
        f'<strong style="font-size:0.95rem;">{lab}:</strong> {body}</p>',
        unsafe_allow_html=True,
    )


def _render_transit_option(
    title: str,
    j,
    wo: float,
    wd: float,
    bd: dict,
    stop_bi: dict[str, tuple[str, str]],
    route_full: dict[str, tuple[str, str, str, str]],
    *,
    db_path: str,
    walking_speed_kmh: float,
    expanded: bool,
) -> None:
    """Numbered steps; stop_id on bus stops; xfer+bus one total time; optional walk between legs."""
    n_xf = len(j.legs) - 1
    xf_each = (bd["transfer_min"] / n_xf) if n_xf else 0.0
    w_o = float(bd.get("walk_origin_min", 0) or 0)
    w_d = float(bd.get("walk_dest_min", 0) or 0)

    coords = _load_stop_coords_cached(db_path)

    with st.expander(title, expanded=expanded):
        _result_header(title, j, float(bd.get("total_min", 0.0) or 0.0))
        prior = False
        step_i = 1

        def _between_steps() -> None:
            nonlocal prior
            if prior:
                st.divider()
            prior = True

        xfer_bus_seq = 0

        if w_o >= 0.5 or wo >= 0.02:
            _between_steps()
            _step_header(step_i, "Walk to board · 步行到上車", w_o, _CLR_WALK)
            step_i += 1
            be, bt = _stop_pair(stop_bi, j.legs[0].from_stop)
            _biline_compact(be, bt, j.legs[0].from_stop)

        for li, leg in enumerate(j.legs):
            o_en, d_en, o_tc, d_tc = route_full.get(leg.route_key, ("", "", "", ""))
            tw_en, tw_tc = toward_terminal_bilingual(
                o_en, d_en, o_tc, d_tc, leg.direction
            )
            n_pass = len(leg.stops_board_to_alight)
            leg_m = bd["per_leg_bus_min"][li]
            op = leg.company or "Bus"

            if li > 0 and n_xf > 0:
                prev = j.legs[li - 1]
                w_km = walk_km_between_stops(prev.to_stop, leg.from_stop, coords)
                if w_km is None:
                    _muted("Transfer walk distance unavailable for this stop pair.")
                elif w_km >= _TRANSFER_WALK_KM:
                    _between_steps()
                    w_min = (w_km / max(walking_speed_kmh, 0.1)) * 60.0
                    _step_header(
                        step_i,
                        "Walk between buses · 巴士之間步行",
                        w_min,
                        _CLR_WALK,
                    )
                    step_i += 1
                    _label_colon_line(
                        "From · 由",
                        *_stop_pair(stop_bi, prev.to_stop),
                        prev.to_stop,
                    )
                    _label_colon_line(
                        "To · 往",
                        *_stop_pair(stop_bi, leg.from_stop),
                        leg.from_stop,
                    )

            _between_steps()
            if li > 0 and n_xf > 0:
                xfer_bus_seq += 1
                chip_alt = _CLR_XF if xfer_bus_seq % 2 else _CLR_BUS
                total_leg = float(xf_each) + float(leg_m)
                _step_header_xfer_bus(step_i, total_leg, chip_color=chip_alt)
            else:
                _step_header(step_i, "Bus · 巴士", leg_m, _CLR_BUS)
            step_i += 1
            _line_route_row(op, leg.route_id, tw_en, tw_tc)
            _label_colon_line(
                "Board · 上",
                *_stop_pair(stop_bi, leg.from_stop),
                leg.from_stop,
            )
            if n_pass > 1:
                _muted(f"{n_pass} stops · {n_pass} 站")
            _label_colon_line(
                "Alight · 落",
                *_stop_pair(stop_bi, leg.to_stop),
                leg.to_stop,
            )

        if w_d >= 0.5 or wd >= 0.02:
            _between_steps()
            _step_header(step_i, "Walk to destination · 步行到目的地", w_d, _CLR_WALK)
            step_i += 1
            fe, ft = _stop_pair(stop_bi, j.legs[-1].to_stop)
            _biline_compact(fe, ft, j.legs[-1].to_stop)


def _pick_endpoint_unified(
    *,
    title: str,
    key_prefix: str,
    clusters: list[dict],
    db_path: str,
    nominatim_url: str,
    map_center_lat: float,
    map_center_lng: float,
    placeholder: str,
    walk_minutes: float,
    walking_speed_kmh: float,
    max_catchment_stop_ids: int,
) -> tuple[list[str] | None, float | None, float | None]:
    """One text field + Search: stop substring matches and OSM place (walking catchment)."""
    st.markdown(f"### {title}")
    r_km = walk_radius_km(walk_minutes, walking_speed_kmh)
    q = st.text_input(
        "Search (stop name / ID, or building · address · place)",
        key=f"{key_prefix}_q",
        placeholder=placeholder,
    )
    c_btn, _ = st.columns([1, 4])
    with c_btn:
        search_clicked = st.button("Search", key=f"{key_prefix}_search", type="primary")

    if search_clicked:
        opts: list[dict] = []
        qt = (q or "").strip()
        if not qt:
            st.warning("Enter a stop name, ID, or place before Search.")
        fo = _filter_clusters(clusters, qt, limit=20) if qt else []
        for c in fo:
            opts.append(
                {
                    "kind": "stop",
                    "label": f"🚏 {c['label']}",
                    "stop_ids": list(c["stop_ids"]),
                    "ref_lat": float(c["lat"]),
                    "ref_lng": float(c["lng"]),
                }
            )
        geo = resolve_place_lat_lng(qt, base_url=nominatim_url) if qt else None
        if geo:
            la, ln, disp = geo
            within = clusters_within_walk_radius(
                db_path,
                la,
                ln,
                walk_minutes=walk_minutes,
                walking_speed_kmh=walking_speed_kmh,
            )
            ids = catchment_stop_ids_ordered(
                within, max_stop_ids=max_catchment_stop_ids
            )
            if ids:
                short = disp[:90] + ("…" if len(disp) > 90 else "")
                opts.append(
                    {
                        "kind": "place",
                        "label": f"📍 {short} — ~{walk_minutes:.0f} min walk (≤ {r_km:.2f} km)",
                        "stop_ids": ids,
                        "ref_lat": la,
                        "ref_lng": ln,
                        "detail": disp,
                    }
                )
        st.session_state[f"{key_prefix}_opts"] = opts
        if not opts:
            st.warning(
                "No stop rows matched and OpenStreetMap did not resolve this text. Try other words or use manual coordinates below."
            )

    opts_key = f"{key_prefix}_opts"
    if opts_key not in st.session_state or not st.session_state[opts_key]:
        st.caption(
            f"Type a **stop** keyword or a **place/address**. One **Search** loads stop matches **and** "
            f"(when possible) an **OSM** location; all stops within ~{walk_minutes:.0f} min walk (~{r_km:.2f} km) "
            f"from a place are used as routing candidates."
        )
        with st.expander("Manual latitude / longitude"):
            c_la, c_ln = st.columns(2)
            with c_la:
                mlat = st.number_input(
                    "Latitude",
                    format="%.5f",
                    value=map_center_lat,
                    key=f"{key_prefix}_mlat",
                )
            with c_ln:
                mlng = st.number_input(
                    "Longitude",
                    format="%.5f",
                    value=map_center_lng,
                    key=f"{key_prefix}_mlng",
                )
            if st.button(
                "Use coordinates & walking catchment", key=f"{key_prefix}_manual"
            ):
                if not _hk_bounds(mlat, mlng):
                    st.error("Coordinates look outside Hong Kong bounds.")
                else:
                    within = clusters_within_walk_radius(
                        db_path,
                        mlat,
                        mlng,
                        walk_minutes=walk_minutes,
                        walking_speed_kmh=walking_speed_kmh,
                    )
                    ids = catchment_stop_ids_ordered(
                        within, max_stop_ids=max_catchment_stop_ids
                    )
                    if not ids:
                        st.warning(f"No stops within ~{r_km:.2f} km of this point.")
                    else:
                        st.session_state[opts_key] = [
                            {
                                "kind": "manual",
                                "label": f"📌 Manual pin — ~{walk_minutes:.0f} min walk ({len(ids)} stop IDs)",
                                "stop_ids": ids,
                                "ref_lat": mlat,
                                "ref_lng": mlng,
                            }
                        ]
        return None, None, None

    options: list[dict] = st.session_state[opts_key]
    labels = [o["label"] for o in options]
    pick = st.selectbox(
        "Pick result",
        range(len(options)),
        format_func=lambda i: labels[i],
        key=f"{key_prefix}_pick",
    )
    row = options[pick]
    if row.get("detail") and row["kind"] == "place":
        st.caption(row["detail"][:280] + ("…" if len(row["detail"]) > 280 else ""))
    return row["stop_ids"], row["ref_lat"], row["ref_lng"]


def main():
    st.title("🧭 Trip planner")
    st.caption(
        "Each side uses **one search** (stop keywords **or** a place/address). Pick a result, then **Plan journey**. "
        "Options are sorted by **estimated total time** (rough: on-bus distance, walking to stops, time at each interchange)."
    )

    params = load_config()
    db_path = params["database"]["path"]
    if not os.path.isabs(db_path):
        db_path = os.path.join(_root, db_path)

    if not os.path.isfile(db_path):
        st.error("Database not found. Run `yuutraffic --update` first.")
        return

    clusters = _load_clusters_cached(db_path)
    if not clusters:
        st.warning("No stops in database.")
        return

    nominatim_url = params.get("api", {}).get(
        "nominatim_search_url", "https://nominatim.openstreetmap.org/search"
    )
    tp = params.get("trip_planner") or {}
    walk_minutes = float(tp.get("walk_minutes", 15))
    walking_speed_kmh = float(tp.get("walking_speed_kmh", 5))
    max_catchment = int(tp.get("max_catchment_stop_ids", 400))
    max_transfers = int(tp.get("max_transfers", 3))
    top_results = int(tp.get("top_results", 5))
    max_direct_results = int(tp.get("max_direct_results", 3))
    routing_tp = float(tp.get("routing_transfer_penalty", 8))
    routing_slack = float(tp.get("routing_cost_slack", 4))
    routing_max_alt = int(tp.get("routing_max_alternatives", 80))
    eta_bus_kmh = float(tp.get("avg_bus_speed_kmh", 17))
    eta_xfer_min = float(tp.get("minutes_per_transfer", 4))
    eta_fallback_hop = float(tp.get("fallback_minutes_per_bus_hop", 2.4))
    results_extra_min = float(tp.get("results_max_extra_minutes_vs_best", 22))
    results_ratio = float(tp.get("results_max_ratio_vs_best", 1.38))
    mc = params.get("map", {}).get("center", {}) or {}
    map_center_lat = float(mc.get("lat", 22.3193))
    map_center_lng = float(mc.get("lng", 114.1694))

    c1, c2 = st.columns(2)
    with c1:
        origin_ids, o_lat, o_lng = _pick_endpoint_unified(
            title="Origin",
            key_prefix="tp_o",
            clusters=clusters,
            db_path=db_path,
            nominatim_url=nominatim_url,
            map_center_lat=map_center_lat,
            map_center_lng=map_center_lng,
            placeholder="e.g. TW10 旺角, Langham Place, IFC Central…",
            walk_minutes=walk_minutes,
            walking_speed_kmh=walking_speed_kmh,
            max_catchment_stop_ids=max_catchment,
        )
    with c2:
        dest_ids, d_lat, d_lng = _pick_endpoint_unified(
            title="Destination",
            key_prefix="tp_d",
            clusters=clusters,
            db_path=db_path,
            nominatim_url=nominatim_url,
            map_center_lat=map_center_lat,
            map_center_lng=map_center_lng,
            placeholder="e.g. Central Pier, 中環, Hong Kong Station…",
            walk_minutes=walk_minutes,
            walking_speed_kmh=walking_speed_kmh,
            max_catchment_stop_ids=max_catchment,
        )

    if not origin_ids or not dest_ids:
        st.info("Set both origin and destination to plan a journey.")
        return

    o_set, d_set = set(origin_ids), set(dest_ids)
    if o_set & d_set:
        st.error(
            "Origin and destination overlap — pick two different areas or narrow search stops."
        )
        return

    with st.expander("Technical: stop IDs used for this search"):
        st.code(
            json.dumps(
                {
                    "origin_count": len(origin_ids),
                    "destination_count": len(dest_ids),
                    "origin_sample": origin_ids[:20],
                    "destination_sample": dest_ids[:20],
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    if st.button("Plan journey", type="primary"):
        stop_bi = _load_stop_names_bi_cached(db_path)
        route_full = _load_route_full_cached(db_path)
        all_j = find_journeys(
            db_path,
            origin_ids,
            dest_ids,
            max_transfers=max_transfers,
            transfer_penalty=routing_tp,
            cost_slack=routing_slack,
            max_alternatives=routing_max_alt,
        )
        if not all_j:
            st.info(
                "No journey found with the current stop candidates. "
                "Try widening walk time, different areas, or fewer cap limits in parameters."
            )
        else:
            direct_rows, xfer_rows = rank_journeys_for_trip_planner(
                all_j,
                origin_ref_lat=o_lat,
                origin_ref_lng=o_lng,
                dest_ref_lat=d_lat,
                dest_ref_lng=d_lng,
                db_path=db_path,
                top_n=top_results,
                max_direct_results=max_direct_results,
                max_extra_minutes_vs_best=results_extra_min,
                max_ratio_vs_best=results_ratio,
                avg_bus_speed_kmh=eta_bus_kmh,
                walking_speed_kmh=walking_speed_kmh,
                minutes_per_transfer=eta_xfer_min,
                fallback_minutes_per_bus_hop=eta_fallback_hop,
            )
            if not direct_rows and not xfer_rows:
                st.warning(
                    "No routes passed the time filter — try relaxing `trip_planner` result limits in parameters."
                )
            else:
                st.caption(
                    "Options are ranked by approximate total time. Identical physical trips across operators "
                    "keep the faster estimate. Times are approximate and not timetable-based."
                )
                ranked_rows = list(direct_rows) + list(xfer_rows)
                if ranked_rows:
                    st.markdown("---")
                    st.markdown("### Options")
                for i, (j, wo, wd, _h, _nxf, _eta, bd) in enumerate(
                    ranked_rows, start=1
                ):
                    title = f"{i}"
                    _render_transit_option(
                        title,
                        j,
                        wo,
                        wd,
                        bd,
                        stop_bi,
                        route_full,
                        db_path=db_path,
                        walking_speed_kmh=walking_speed_kmh,
                        expanded=(i == 1),
                    )


main()
