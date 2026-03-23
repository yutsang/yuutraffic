"""
Hong Kong KMB Transport - Production App
Enhanced Streamlit application for exploring KMB bus routes and stops
"""

import os
import sys

# Add the pipelines to the path
sys.path.append(os.path.join(os.path.dirname(__file__), "pipelines", "web_app"))

import folium
import pandas as pd
import streamlit as st
from pipelines.web_app.nodes import (
    create_enhanced_route_map,
    get_route_stops_with_directions,
    get_sorted_routes,
    load_traffic_data,
)
from streamlit_folium import folium_static

# Constants
MAX_NAME_LENGTH = 20
TRUNCATED_SUFFIX = "..."

# Page configuration
st.set_page_config(
    page_title="Hong Kong KMB Transport - Production",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Production CSS - Theme adaptive and clean
st.markdown(
    """
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
        font-weight: 600;
    }
    .route-info-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 1rem;
        margin-bottom: 2rem;
    }
    .route-info-card {
        padding: 1rem;
        border-radius: 0.5rem;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        text-align: center;
    }
    .route-info-card h3 {
        margin: 0 0 0.5rem 0;
        color: #1f77b4;
        font-size: 1.1rem;
    }
    .route-info-card p {
        margin: 0;
        font-size: 0.9rem;
        opacity: 0.8;
    }
    .direction-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 1rem;
        font-size: 0.8rem;
        font-weight: bold;
        margin: 0.2rem;
    }
    .outbound {
        background-color: #28a745;
        color: white;
    }
    .inbound {
        background-color: #dc3545;
        color: white;
    }
    .stats-container {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 1rem;
    }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600)
def load_cached_data():
    """Load and cache KMB data"""
    return load_traffic_data()


def format_route_option(route_row):
    """Format route option for display"""
    origin = route_row.get("origin", "N/A")
    destination = route_row.get("destination", "N/A")
    # Truncate long names
    if len(origin) > MAX_NAME_LENGTH:
        origin = origin[: MAX_NAME_LENGTH - len(TRUNCATED_SUFFIX)] + TRUNCATED_SUFFIX
    if len(destination) > MAX_NAME_LENGTH:
        destination = (
            destination[: MAX_NAME_LENGTH - len(TRUNCATED_SUFFIX)] + TRUNCATED_SUFFIX
        )

    return f"{route_row['route_id']} | {origin} → {destination}"


def get_available_directions(route_stops):
    """Get available directions for a route"""
    if route_stops.empty:
        return []

    directions = route_stops["direction"].unique()
    direction_info = []

    for direction in sorted(directions):
        direction_name = "Outbound" if direction == 1 else "Inbound"
        stop_count = len(route_stops[route_stops["direction"] == direction])
        direction_info.append(
            {"direction": direction, "name": direction_name, "stops": stop_count}
        )

    return direction_info


def _setup_header():
    """Setup application header"""
    st.markdown(
        '<h1 class="main-header">🚌 Hong Kong KMB Transport</h1>', unsafe_allow_html=True
    )
    st.markdown(
        '<p style="text-align: center; opacity: 0.7; margin-bottom: 2rem;">Production-ready route explorer with complete data coverage</p>',
        unsafe_allow_html=True,
    )


def _load_and_validate_data():
    """Load and validate route data"""
    with st.spinner("Loading KMB route data..."):
        routes_df, stops_df = load_cached_data()

    if routes_df.empty:
        st.error("❌ No route data available. Please check database connection.")
        return None, None

    return routes_df, stops_df


def _setup_sidebar_controls(sorted_routes):
    """Setup sidebar controls for route selection"""
    st.sidebar.header("🚌 Route Selection")

    search_term = st.sidebar.text_input(
        "🔍 Search Routes",
        placeholder="e.g., 219X, 24, Central",
        help="Search by route number or destination",
    )

    # Filter routes based on search
    if search_term:
        mask = (
            sorted_routes["route_id"].str.contains(search_term, case=False, na=False)
            | sorted_routes["origin"].str.contains(search_term, case=False, na=False)
            | sorted_routes["destination"].str.contains(
                search_term, case=False, na=False
            )
        )
        filtered_routes = sorted_routes[mask]
    else:
        filtered_routes = sorted_routes

    return filtered_routes, search_term


def _handle_route_selection(filtered_routes):
    """Handle route selection logic"""
    if filtered_routes.empty:
        st.sidebar.warning("No routes found matching your search")
        return None, None, pd.DataFrame(), 1, None

    route_options = [
        format_route_option(row) for idx, row in filtered_routes.iterrows()
    ]

    selected_route_display = st.sidebar.selectbox(
        "Select Route",
        ["None"] + route_options,
        help=f"Found {len(filtered_routes)} routes",
    )

    if selected_route_display == "None":
        return None, None, pd.DataFrame(), 1, None

    # Extract route ID
    selected_route_id = selected_route_display.split(" | ")[0]
    selected_route_info = filtered_routes[
        filtered_routes["route_id"] == selected_route_id
    ].iloc[0]

    # Load route stops with directions
    with st.spinner("Loading route stops..."):
        route_stops = get_route_stops_with_directions(selected_route_id)

    if route_stops.empty:
        st.sidebar.warning("⚠️ No stops found for this route")
        return selected_route_id, selected_route_info, route_stops, 1, None

    return selected_route_id, selected_route_info, route_stops, None, None


def _handle_direction_selection(route_stops):
    """Handle direction selection logic"""
    available_directions = get_available_directions(route_stops)

    if len(available_directions) > 1:
        direction_options = [
            f"{d['name']} ({d['stops']} stops)" for d in available_directions
        ]
        selected_direction_display = st.sidebar.selectbox(
            "Select Direction",
            direction_options,
            help="Choose route direction",
        )
        selected_direction = available_directions[
            direction_options.index(selected_direction_display)
        ]["direction"]
    else:
        selected_direction = available_directions[0]["direction"]
        st.sidebar.info(f"Single direction: {available_directions[0]['name']}")

    return selected_direction


def _handle_stop_selection(route_stops, selected_direction):
    """Handle stop selection logic"""
    direction_stops = route_stops[
        route_stops["direction"] == selected_direction
    ].sort_values("sequence")

    if direction_stops.empty:
        return None

    stop_options = [
        f"Stop {row['sequence']}: {row['stop_name']}"
        for idx, row in direction_stops.iterrows()
    ]
    selected_stop_display = st.sidebar.selectbox(
        "Highlight Stop (Optional)", ["None"] + stop_options
    )

    if selected_stop_display == "None":
        return None

    stop_seq = int(selected_stop_display.split(":")[0].replace("Stop ", ""))
    selected_stop_row = direction_stops[direction_stops["sequence"] == stop_seq]
    if not selected_stop_row.empty:
        return selected_stop_row.iloc[0]["stop_id"]

    return None


def _setup_sidebar_footer(routes_df, stops_df):
    """Setup sidebar footer with cache button and stats"""
    # Clear cache button
    if st.sidebar.button("🔄 Clear Cache & Refresh"):
        st.cache_data.clear()
        st.rerun()

    # Database stats
    st.sidebar.markdown("---")
    stops_count = len(stops_df) if stops_df is not None else 0
    st.sidebar.markdown(
        f"""
    <div class="stats-container">
        <h4 style="margin: 0 0 0.5rem 0;">📊 Database Status</h4>
        <p>Routes: {len(routes_df)}</p>
        <p>Stops: {stops_count}</p>
        <p>Coverage: 100%</p>
    </div>
    """,
        unsafe_allow_html=True,
    )


def _display_route_info(selected_route_info, route_stops, selected_direction):
    """Display route information"""
    direction_name = "Outbound" if selected_direction == 1 else "Inbound"
    direction_stops_count = len(
        route_stops[route_stops["direction"] == selected_direction]
    )
    total_directions = len(route_stops["direction"].unique())

    st.markdown(
        f"""
    <div class="route-info-grid">
        <div class="route-info-card">
            <h3>🚌 Route</h3>
            <p>{selected_route_info['route_id']}</p>
        </div>
        <div class="route-info-card">
            <h3>📍 Origin</h3>
            <p>{selected_route_info['origin']}</p>
        </div>
        <div class="route-info-card">
            <h3>🎯 Destination</h3>
            <p>{selected_route_info['destination']}</p>
        </div>
        <div class="route-info-card">
            <h3>🚏 Stops</h3>
            <p>{direction_stops_count} ({direction_name})</p>
        </div>
        <div class="route-info-card">
            <h3>↔️ Directions</h3>
            <p>{total_directions} available</p>
        </div>
        <div class="route-info-card">
            <h3>⚙️ Service Type</h3>
            <p>{selected_route_info.get('service_type', 'N/A')}</p>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def _render_direction_badges(route_stops, selected_direction):
    available_directions = get_available_directions(route_stops)
    direction_badges = []
    for d in available_directions:
        badge_class = "outbound" if d["direction"] == 1 else "inbound"
        active = "🔸 " if d["direction"] == selected_direction else ""
        direction_badges.append(
            f'<span class="direction-badge {badge_class}">{active}{d["name"]} ({d["stops"]} stops)</span>'
        )
    st.markdown(
        f"**Available Directions:** {''.join(direction_badges)}",
        unsafe_allow_html=True,
    )


def _render_map_and_stops_table(route_stops, selected_stop_id, selected_direction):
    st.header("🗺️ Interactive Route Map")
    map_obj = create_enhanced_route_map(
        route_stops, selected_stop_id, selected_direction
    )
    folium_static(map_obj, width=1200, height=600)
    st.header("📍 Route Stops")
    direction_stops = route_stops[
        route_stops["direction"] == selected_direction
    ].sort_values("sequence")
    if not direction_stops.empty:
        display_stops = direction_stops[["sequence", "stop_name", "stop_id"]].copy()
        display_stops.columns = ["Sequence", "Stop Name", "Stop ID"]
        if selected_stop_id:

            def highlight_selected(row):
                if row["Stop ID"] == selected_stop_id:
                    return ["background-color: #ffeb3b"] * len(row)
                return [""] * len(row)

            st.dataframe(
                display_stops.style.apply(highlight_selected, axis=1),
                use_container_width=True,
                height=400,
            )
        else:
            st.dataframe(display_stops, use_container_width=True, height=400)
    else:
        st.warning("No stops available for the selected direction")


def _render_default_view(routes_df, stops_df):
    st.header("🗺️ Route Explorer")
    st.info(
        "👆 Select a route from the sidebar to view its path, stops, and real-time information."
    )
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Routes", len(routes_df), "100% coverage")
    with col2:
        stops_count = len(stops_df) if stops_df is not None else 0
        st.metric("Total Stops", stops_count, "All regions")
    with col3:
        routes_with_stops = routes_df[
            routes_df["route_id"].isin(
                [
                    route_id
                    for route_id in routes_df["route_id"]
                    if not get_route_stops_with_directions(route_id).empty
                ]
            )
        ]
        st.metric("Active Routes", len(routes_with_stops), "Ready to explore")
    with col4:
        st.metric("Port", "8508", "Easy debugging")
    default_map = folium.Map(
        location=[22.3193, 114.1694], zoom_start=11, tiles="OpenStreetMap"
    )
    folium_static(default_map, width=1200, height=400)


def main():
    """Main application function"""
    _setup_header()

    # Load data
    routes_df, stops_df = _load_and_validate_data()
    if routes_df is None:
        return

    # Sort routes naturally
    sorted_routes = get_sorted_routes(routes_df)

    # Setup sidebar controls
    filtered_routes, search_term = _setup_sidebar_controls(sorted_routes)

    # Handle route selection
    (
        selected_route_id,
        selected_route_info,
        route_stops,
        selected_direction,
        selected_stop_id,
    ) = _handle_route_selection(filtered_routes)

    # Handle direction and stop selection if route is selected
    if selected_route_id and not route_stops.empty and selected_direction is None:
        selected_direction = _handle_direction_selection(route_stops)
        selected_stop_id = _handle_stop_selection(route_stops, selected_direction)

    # Setup sidebar footer
    _setup_sidebar_footer(routes_df, stops_df)

    # Main content
    if selected_route_id and not route_stops.empty and selected_direction is not None:
        _display_route_info(selected_route_info, route_stops, selected_direction)
        _render_direction_badges(route_stops, selected_direction)
        _render_map_and_stops_table(route_stops, selected_stop_id, selected_direction)
    else:
        _render_default_view(routes_df, stops_df)


if __name__ == "__main__":
    main()
