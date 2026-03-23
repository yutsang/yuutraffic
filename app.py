"""
Traffic ETA - Hong Kong Public Transport Explorer
Streamlit app for exploring KMB routes, maps, and stop information.
"""

import logging
import os
import re
import sys
import traceback

# Ensure project root and src on path when run directly
_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)
_src = os.path.join(_dir, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from yuutraffic.web import (
    create_enhanced_route_map,
    create_route_options_with_directions,
    fetch_etas_for_stops,
    prepare_direction_stops,
    format_route_type_badge,
    get_first_run_status,
    get_route_stops_with_directions,
    get_sorted_routes,
    load_all_route_stops,
    load_traffic_data,
    mark_first_run_complete,
    should_update_data,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")

st.set_page_config(
    page_title="Traffic ETA - Hong Kong Transport",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        "Get Help": "https://github.com/your-repo/issues",
        "Report a bug": "https://github.com/your-repo/issues",
        "About": "# Hong Kong Transport Explorer\n\nExplore Hong Kong's public transport routes with interactive maps and real-time information.",
    },
)

st.markdown(
    """
<style>
    :root { --bg-primary: #ffffff; --bg-secondary: #f8f9fa; --bg-accent: #e3f2fd; --text-primary: #333333; --text-secondary: #666666; --text-muted: #6c757d; --border-color: #e0e0e0; --border-light: #e9ecef; --blue: #007bff; --green: #28a745; --orange: #fd7e14; --red: #dc3545; }
    @media (prefers-color-scheme: dark) { :root { --bg-primary: #0e1117; --bg-secondary: #262730; --bg-accent: rgba(33, 150, 243, 0.1); --text-primary: #ffffff; --text-secondary: #cccccc; --text-muted: #aaaaaa; --border-color: rgba(255,255,255,0.1); --border-light: rgba(255,255,255,0.05); --blue: #2196f3; } }
    .main .block-container { padding: 1rem clamp(1rem, 3vw, 2rem) 1.5rem !important; max-width: 100% !important; width: 100% !important; }
    html, body, .stApp { min-height: 100% !important; overflow-x: hidden !important; }
    .main { min-height: 100% !important; overflow: visible !important; }
    .stMarkdown, .stColumns, .stColumn { margin-bottom: 0 !important; }
    .stColumn:nth-child(2) .stMarkdown, .stColumn:nth-child(2) div[data-testid="stMarkdownContainer"] { margin-bottom: 8px !important; padding: 0 !important; }
    .stColumns, .stColumn { height: auto !important; }
    .stats-container { background: var(--bg-secondary); padding: 1rem; border-radius: 8px; margin-bottom: 1rem; border: 1px solid var(--border-color); }
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 1rem; margin-top: 1rem; }
    .stat-item { background: var(--bg-accent); padding: 1rem; border-radius: 6px; text-align: center; border: 1px solid var(--border-light); }
    .stat-number { font-size: 1.5rem; font-weight: bold; color: var(--blue); display: block; }
    .stat-label { font-size: 0.9rem; color: var(--text-muted); margin-top: 0.3rem; }
    .route-info-container { background: var(--bg-secondary); padding: 0.8rem; border-radius: 8px; margin-bottom: 1rem; border: 1px solid var(--border-color); }
    .stButton > button { padding: 0.3rem 0.8rem !important; font-size: 0.8rem !important; height: auto !important; min-height: 2rem !important; }
    .route-info-section .stColumns { gap: 0.5rem !important; }
    .route-info-section .stColumn, .route-info-section .stColumn > div, .route-info-section .stColumn .element-container, .route-info-section .stColumn .stMarkdown, .route-info-section .stColumn .stButton, .route-info-section .stColumn .stButton > div { padding: 0 !important; margin: 0 !important; background: transparent !important; min-height: auto !important; height: auto !important; }
    .route-info-container:hover { border-color: var(--blue); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    .route-info-row { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
    .route-info-left { display: flex; align-items: center; gap: 0.8rem; flex: 1; flex-wrap: wrap; }
    .route-detail { background: var(--bg-accent); padding: 0.4rem 0.8rem; border-radius: 16px; border: 1px solid var(--border-color); font-size: 0.8rem; color: var(--text-primary); white-space: nowrap; min-width: 100px; text-align: center; }
    .route-detail.route-number { border-color: var(--blue); color: var(--blue); font-weight: bold; }
    .route-detail.route-type { border-color: var(--green); color: var(--green); }
    .route-detail.route-origin { border-color: var(--orange); color: var(--orange); }
    .route-detail.route-destination { border-color: var(--red); color: var(--red); }
    .main-content { max-width: 100%; padding: 0; }
    .map-stops-container { display: flex; gap: 1rem; min-height: clamp(420px, 58vh, 760px); margin: 1rem 0; align-items: stretch; }
    .map-stops-container > div, .map-stops-container .stColumn { align-items: flex-start !important; }
    .map-container { border-radius: 8px; border: 1px solid var(--border-color); overflow: hidden; background: var(--bg-secondary); }
    .stops-container { background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; }
    .welcome-container { text-align: center; padding: 3rem 2rem; background: var(--bg-secondary); border-radius: 12px; border: 1px solid var(--border-color); margin: 2rem auto; max-width: 600px; }
    .welcome-icon { font-size: 4rem; margin-bottom: 1rem; color: var(--blue); }
    .stButton > button { border-radius: 8px !important; border: 1px solid var(--border-color) !important; font-weight: 500 !important; }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300)
def initialize_app():
    try:
        return load_traffic_data()
    except Exception as e:
        st.error(f"Error initializing app: {str(e)}")
        return None, None


@st.cache_data(ttl=300)
def get_preloaded_route_stops():
    """Load all route stops at startup so route selection is instant."""
    return load_all_route_stops()


@st.cache_data(ttl=300)
def get_cached_route_options(routes_df):
    return create_route_options_with_directions(routes_df)


def split_name_for_box(name, max_len=25):
    if len(name) <= max_len:
        return name
    mid = len(name) // 2
    split_at = name.rfind(" ", 0, mid + 5)
    if split_at == -1:
        split_at = mid
    return name[:split_at] + "<br>" + name[split_at + 1:]


# UI strings for language toggle
UI = {
    "en": {
        "title": "Hong Kong Public Transport Explorer",
        "search_routes": "Search Routes",
        "search_placeholder": "Route no., place, 小巴, MTR bus, Mong Kok…",
        "select_route": "Select route",
        "route_info": "Route Information",
        "route": "Route",
        "type": "Type",
        "from_": "From",
        "to": "To",
        "direction": "Direction",
        "route_stops": "Route Stops",
        "eta_refresh_hint": "ETAs refresh every 1 min",
        "refresh": "Refresh",
        "eta_arriving": "Arriving",
        "eta_na": "—",
        "search_other": "Search Other Routes",
        "reverse": "REVERSE",
        "key_stats": "Key Statistics",
        "routes": "Routes",
        "stops": "Stops",
        "destinations": "Destinations",
        "welcome_title": "Welcome to Hong Kong Transport Explorer!",
        "welcome_p": "Select a route from the dropdown above to view its interactive map, route information, and stop details.",
        "no_match": "No matches. Try a different search.",
    },
    "tc": {
        "title": "香港公共交通工具探索",
        "search_routes": "搜索路線",
        "search_placeholder": "路線號、地點、小巴、港鐵巴士、旺角…",
        "select_route": "選擇路線",
        "route_info": "路線資訊",
        "route": "路線",
        "type": "類型",
        "from_": "起點",
        "to": "終點",
        "direction": "方向",
        "route_stops": "巴士站",
        "eta_refresh_hint": "預計到站每分鐘更新",
        "refresh": "更新",
        "eta_arriving": "即將到達",
        "eta_na": "—",
        "search_other": "搜尋其他路線",
        "reverse": "反轉",
        "key_stats": "主要統計",
        "routes": "路線數",
        "stops": "車站數",
        "destinations": "目的地數",
        "welcome_title": "歡迎使用香港交通工具探索！",
        "welcome_p": "從上方下拉選單選擇路線，查看互動地圖、路線資訊及車站詳情。",
        "no_match": "沒有相符結果，請嘗試其他搜尋。",
    },
}


def _t(key: str) -> str:
    lang = st.session_state.get("lang", "en")
    return UI.get(lang, UI["en"]).get(key, UI["en"].get(key, key))


def _initialize_session_state():
    if "selected_route" not in st.session_state:
        st.session_state.selected_route = None
    if "selected_direction" not in st.session_state:
        st.session_state.selected_direction = None
    if "lang" not in st.session_state:
        st.session_state.lang = "en"
    if "eta_loaded" not in st.session_state:
        st.session_state.eta_loaded = {}
    if "eta_dict" not in st.session_state:
        st.session_state.eta_dict = {}


def _setup_header():
    st.title(f"🗺️ {_t('title')}")
    st.header(f"🔍 {_t('search_routes')}")


def _normalize_search_query(q: str) -> tuple[str, list[str]]:
    """Lowercase, map common Chinese / English operator phrases, tokenize."""
    s = (q or "").lower().strip()
    repl = (
        ("港鐵巴士", " mtr "),
        ("港铁巴士", " mtr "),
        ("mtr bus", " mtr "),
        ("綠色小巴", " gmb "),
        ("绿色小巴", " gmb "),
        ("專線小巴", " gmb "),
        ("专线小巴", " gmb "),
        ("green minibus", " gmb "),
        ("紅色小巴", " rmb "),
        ("红色小巴", " rmb "),
        ("red minibus", " rmb "),
    )
    for a, b in repl:
        s = s.replace(a.lower(), b)
    s = re.sub(r"[\s,，、]+", " ", s).strip()
    tokens = [t for t in s.split() if t]
    return s, tokens


def _numeric_token_matches_route(token: str, route_id: str) -> bool:
    """So '65' ranks 65 / 65X above 650 / A65."""
    if not token.isdigit():
        return False
    rid = str(route_id).lower()
    if not rid.startswith(token):
        return False
    rest = rid[len(token) :]
    if not rest:
        return True
    return not rest[0].isdigit()


def _score_route_option(o: dict, tokens: list[str], norm: str) -> int:
    hay = " ".join(
        [
            str(o.get("route_id", "")),
            str(o.get("display_route_id", "")),
            str(o.get("text", "")),
            str(o.get("origin", "")),
            str(o.get("destination", "")),
            str(o.get("origin_tc", "")),
            str(o.get("destination_tc", "")),
            str(o.get("depot_name", "")),
            str(o.get("company", "")),
            str(o.get("route_name", "")),
        ]
    ).lower()
    disp = str(o.get("display_route_id") or o.get("route_id") or "").lower()
    if not tokens:
        return 50 if norm in hay else 0
    score = 0
    for t in tokens:
        if t not in hay:
            return -1
        score += 8
        if t == disp:
            score += 120
        elif disp.startswith(t):
            score += 85
        elif _numeric_token_matches_route(t, disp):
            score += 95
        elif t in disp:
            score += 35
    return score


def _filter_route_options(route_options, search_term: str, limit: int = 400):
    """Token-aware filter with scoring: route number prefix, operator keywords, places."""
    if not search_term.strip():
        return route_options[:limit]
    norm, tokens = _normalize_search_query(search_term)
    scored: list[tuple[int, dict]] = []
    for o in route_options:
        sc = _score_route_option(o, tokens, norm)
        if sc < 0:
            continue
        scored.append((sc, o))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("text", ""))))
    return [o for _, o in scored[:limit]]


def _handle_route_selection(route_options):
    st.markdown(f"**🔍 {_t('search_routes')}** — one row: type keywords, then pick route + direction")
    bar = st.columns([1, 1.15], gap="small")
    with bar[0]:
        search = st.text_input(
            "Search",
            key="route_search",
            placeholder=_t("search_placeholder"),
            label_visibility="collapsed",
        )
    filtered = _filter_route_options(route_options, search or "")
    if not filtered:
        st.info(_t("no_match"))
        return None
    option_texts = [o["text"] for o in filtered]
    with bar[1]:
        # Key includes search so when you type "80", dropdown resets and shows 80, 80M, 80K first (not 680)
        selected = st.selectbox(
            f"🚌 {_t('select_route')}",
            option_texts,
            key=f"route_select_{(search or '').strip()}",
            index=0,
            label_visibility="collapsed",
        )
    if not selected:
        return None
    for o in filtered:
        if o["text"] == selected:
            return o
    return None


def _get_current_direction(selected_route_data):
    """Direction comes directly from dropdown selection."""
    return int(selected_route_data.get("direction", 1))


def _is_terminus_stop(name_en: str, name_tc: str) -> bool:
    """Check if stop is a bus terminus (總站)."""
    if not name_en and not name_tc:
        return False
    en = (name_en or "").upper()
    tc = name_tc or ""
    return "BUS TERMINUS" in en or "總站" in tc


def _get_route_endpoints(direction_stops, selected_route_data):
    if not direction_stops.empty:
        first = direction_stops.iloc[0]
        last = direction_stops.iloc[-1]
        # Circular: KMB API has terminus last; bus starts at terminus. If prepare_direction_stops
        # didn't reorder (e.g. different DB schema), swap here so From = terminus.
        if selected_route_data.get("route_type") == "Circular":
            first_terminus = _is_terminus_stop(
                first.get("stop_name", ""), first.get("stop_name_tc", "")
            )
            last_terminus = _is_terminus_stop(
                last.get("stop_name", ""), last.get("stop_name_tc", "")
            )
            if not first_terminus and last_terminus:
                first, last = last, first
        return (
            first["stop_name"],
            last["stop_name"],
            first.get("stop_name_tc", "") or "",
            last.get("stop_name_tc", "") or "",
        )
    return (
        selected_route_data["origin"],
        selected_route_data["destination"],
        selected_route_data.get("origin_tc", "") or "",
        selected_route_data.get("destination_tc", "") or "",
    )


def _display_route_info(selected_route_data, first_stop, last_stop, first_tc, last_tc, current_direction):
    st.subheader(_t("route_info"))
    # Always show both Chi and Eng
    if first_tc:
        from_box = split_name_for_box(first_tc)
        if first_stop:
            from_box += f"<br><span style='font-size:0.75em;color:#666;'>{first_stop}</span>"
    else:
        from_box = split_name_for_box(first_stop)
        if first_tc:
            from_box += f"<br><span style='font-size:0.75em;color:#666;'>{first_tc}</span>"
    if last_tc:
        to_box = split_name_for_box(last_tc)
        if last_stop:
            to_box += f"<br><span style='font-size:0.75em;color:#666;'>{last_stop}</span>"
    else:
        to_box = split_name_for_box(last_stop)
        if last_tc:
            to_box += f"<br><span style='font-size:0.75em;color:#666;'>{last_tc}</span>"
    st.markdown(f"""
    <div style="display:flex;gap:0.5rem;align-items:stretch;margin-bottom:1rem;">
        <div style="flex:1;text-align:center;padding:0.3rem;background:var(--bg-secondary);border-radius:6px;border:1px solid var(--border-color);">
            <div style="font-size:0.65rem;color:var(--text-muted);">🚌 {_t('route')}</div>
            <div style="font-size:0.9rem;font-weight:bold;color:var(--blue);">{selected_route_data.get('display_route_id', selected_route_data['route_id'])}</div>
        </div>
        <div style="flex:1;text-align:center;padding:0.3rem;background:var(--bg-secondary);border-radius:6px;border:1px solid var(--border-color);">
            <div style="font-size:0.65rem;color:var(--text-muted);">🏷️ {_t('type')}</div>
            <div style="font-size:0.8rem;font-weight:bold;color:var(--green);">{selected_route_data['route_type']}</div>
        </div>
        <div style="flex:2;text-align:center;padding:0.3rem;background:var(--bg-secondary);border-radius:6px;border:1px solid var(--border-color);">
            <div style="font-size:0.65rem;color:var(--text-muted);">📍 {_t('from_')}</div>
            <div style="font-size:0.75rem;font-weight:bold;color:var(--orange);">{from_box}</div>
        </div>
        <div style="flex:2;text-align:center;padding:0.3rem;background:var(--bg-secondary);border-radius:6px;border:1px solid var(--border-color);">
            <div style="font-size:0.65rem;color:var(--text-muted);">🎯 {_t('to')}</div>
            <div style="font-size:0.75rem;font-weight:bold;color:var(--red);">{to_box}</div>
        </div>
        <div style="flex:1;text-align:center;padding:0.3rem;background:var(--bg-secondary);border-radius:6px;border:1px solid var(--border-color);">
            <div style="font-size:0.65rem;color:var(--text-muted);">🧭 {_t('direction')}</div>
            <div style="font-size:0.9rem;font-weight:bold;">{current_direction}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _render_map_and_stops(route_key, direction_stops, current_direction, selected_route_data=None):
    eta_key = f"{route_key}_{current_direction}"
    eta_dict = st.session_state.get("eta_dict", {}).get(eta_key, {})
    map_height = 560
    col1, col2 = st.columns([3, 1], gap="medium")
    # Render map and stops first (no ETA block) for faster perceived load
    with col1:
        st.subheader("🗺️ Route Map")
        try:
            map_obj = create_enhanced_route_map(
                direction_stops,
                st.session_state.get("selected_stop_id"),
                current_direction,
                eta_dict=eta_dict,
                lang="tc",  # Map popups: Chi first, Eng second (matches stop list)
                geometry_hash=selected_route_data.get("geometry_hash") if selected_route_data else None,
            )
            st_folium(
                map_obj,
                height=map_height,
                use_container_width=True,
                returned_objects=[],
                key=f"route_map_{route_key}_{current_direction}",
            )
        except Exception as e:
            st.error(f"❌ Error creating map: {str(e)}")
            if os.getenv("DEBUG_MODE", "false").lower() == "true":
                st.text(traceback.format_exc())
    with col2:
        h1, h2 = st.columns([3, 1])
        with h1:
            st.subheader(f"🚏 {_t('route_stops')}")
        with h2:
            if st.button("🔄", key="refresh_etas_btn", use_container_width=True, help=_t("eta_refresh_hint")):
                if "eta_dict" in st.session_state:
                    st.session_state.eta_dict = {}
                st.rerun()
        if not direction_stops.empty:
            html = f"<div style='height:{map_height}px;overflow-y:auto;border:1px solid #e0e0e0;border-radius:8px;background:var(--bg-secondary);padding:8px;'>"
            for idx, stop in enumerate(direction_stops.itertuples(), 1):
                name_en = getattr(stop, "stop_name", "")
                name_tc = getattr(stop, "stop_name_tc", "") or ""
                # Same color for Chi and Eng; stop code (e.g. TW900) shown once
                code_match = re.search(r'\s*\([A-Za-z0-9]+\)\s*$', name_en or name_tc)
                code = code_match.group(0).strip() if code_match else ""
                en_clean = re.sub(r'\s*\([A-Za-z0-9]+\)\s*$', '', (name_en or '')).strip()
                tc_clean = re.sub(r'\s*\([A-Za-z0-9]+\)\s*$', '', (name_tc or '')).strip()
                if name_tc and tc_clean and tc_clean != en_clean:
                    display = f"<span style='color:var(--text-primary);'>{tc_clean}</span><br><span style='font-size:0.95em;color:var(--text-primary);'>{en_clean}</span>"
                    if code:
                        display += f" <span style='font-size:0.9em;color:var(--text-muted);'>{code}</span>"
                else:
                    main = en_clean or tc_clean or name_en or name_tc
                    display = f"<span style='color:var(--text-primary);'>{main}</span>"
                    if code:
                        display += f" <span style='font-size:0.9em;color:var(--text-muted);'>{code}</span>"
                etas = eta_dict.get(stop.stop_id, [])
                eta_str = ", ".join(etas) if etas else "—"
                html += f"<div style='display:flex;align-items:flex-start;gap:0.5rem;padding:0.5rem 0.75rem;border-bottom:1px solid #444;background:var(--bg-primary);font-size:1rem;'><span style='background:#2196f3;color:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-weight:bold;flex-shrink:0;min-width:28px;'>{idx}</span><span style='flex:1;min-width:0;'>{display}<br><span style='font-size:0.8em;color:#28a745;font-weight:500;'>ETA: {eta_str}</span></span></div>"
            html += "</div>"
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.info("⚠️ No stops found for this route.")
    # Fetch ETAs after map/stops rendered (reduces blank page time)
    route_id = selected_route_data.get("route_id", "") if selected_route_data else ""
    if not eta_dict and route_id and not direction_stops.empty:
        stop_ids = direction_stops["stop_id"].tolist()
        seqs = direction_stops["sequence"].astype(int).tolist() if "sequence" in direction_stops.columns else []
        service_type = 1
        if "service_type" in direction_stops.columns and direction_stops["service_type"].notna().any():
            service_type = int(direction_stops["service_type"].iloc[0])
        company = (selected_route_data or {}).get("company", "")
        prov = (selected_route_data or {}).get("provider_route_id") or ""
        prov = str(prov).strip() or None
        try:
            eta_dict = fetch_etas_for_stops(
                route_id,
                stop_ids,
                service_type=service_type,
                minutes_format=True,
                company=company,
                provider_route_id=prov,
                route_direction=current_direction,
                stop_sequences=seqs,
            )
            if eta_dict:
                if "eta_dict" not in st.session_state:
                    st.session_state.eta_dict = {}
                st.session_state.eta_dict[eta_key] = eta_dict
                st.rerun()
        except Exception:
            pass


def _render_welcome_message():
    title = _t("welcome_title")
    p = _t("welcome_p")
    st.markdown(f"""
    <div class="welcome-container">
        <div class="welcome-icon">🚌</div>
        <h2>{title}</h2>
        <p>{p}</p>
        <p><strong>💡</strong> Type to filter or scroll the dropdown to select a route.</p>
    </div>
    """, unsafe_allow_html=True)


def _render_key_statistics(routes_df, stops_df):
    st.divider()
    st.header(f"📊 {_t('key_stats')}")
    try:
        all_dest = set(routes_df["destination"].dropna().unique()) | set(routes_df["origin"].dropna().unique())
    except KeyError:
        all_dest = set(routes_df["destination_en"].dropna().unique()) | set(routes_df["origin_en"].dropna().unique())
    total_routes = len(routes_df)
    total_stops = len(stops_df) if stops_df is not None and not stops_df.empty else 0
    st.markdown(f"""
    <div class="stats-container"><div class="stats-grid">
        <div class="stat-item"><div class="stat-number">{total_routes}</div><div class="stat-label">{_t('routes')}</div></div>
        <div class="stat-item"><div class="stat-number">{total_stops}</div><div class="stat-label">{_t('stops')}</div></div>
        <div class="stat-item"><div class="stat-number">{len(all_dest)}</div><div class="stat-label">{_t('destinations')}</div></div>
    </div></div>
    """, unsafe_allow_html=True)


def main():
    try:
        with st.spinner("Loading transport data..."):
            routes_df, stops_df = initialize_app()
            all_route_stops = get_preloaded_route_stops()
        if routes_df is None or routes_df.empty:
            st.error("❌ No route data available. Please check your data connection.")
            return
    except Exception as e:
        st.error(f"❌ Error loading data: {str(e)}")
        return
    _initialize_session_state()
    _setup_header()
    routes_sorted = get_sorted_routes(routes_df)
    route_options = get_cached_route_options(routes_sorted)
    selected_route_data = _handle_route_selection(route_options)
    if selected_route_data:
        route_key = selected_route_data.get("route_key", selected_route_data["route_id"])
        route_id = selected_route_data["route_id"]
        current_direction = _get_current_direction(selected_route_data)
        st.session_state.selected_route = route_key
        st.session_state.selected_direction = current_direction
        route_stops = all_route_stops.get(route_key, pd.DataFrame())
        if route_stops.empty:
            route_stops = get_route_stops_with_directions(route_key)
        if not route_stops.empty:
            direction_stops = prepare_direction_stops(route_stops, current_direction, route_key)
            first_stop, last_stop, first_tc, last_tc = _get_route_endpoints(direction_stops, selected_route_data)
            _display_route_info(selected_route_data, first_stop, last_stop, first_tc, last_tc, current_direction)
            if not direction_stops.empty:
                _render_map_and_stops(route_key, direction_stops, current_direction, selected_route_data)
        else:
            st.warning("⚠️ No stop data available for this route")
    else:
        _render_welcome_message()
    _render_key_statistics(routes_df, stops_df)


if __name__ == "__main__":
    main()
