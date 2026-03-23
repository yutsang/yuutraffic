"""
Hong Kong KMB Bus Dashboard - Simplified Version
Only route selection and map display with nodes and depots
"""

import json
import os

import folium
import pandas as pd
import requests
import streamlit as st
from api_connectors import HKTransportAPIManager
from streamlit_folium import folium_static

# Page configuration
st.set_page_config(
    page_title="Hong Kong KMB Route Map",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS - Theme adaptive
st.markdown(
    """
<style>
    .main-header {
        font-size: 2rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .route-info-horizontal {
        display: flex;
        flex-wrap: wrap;
        gap: 1rem;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        background-color: var(--background-color);
        border: 1px solid var(--border-color);
    }
    .route-info-item {
        flex: 1;
        min-width: 200px;
        padding: 0.5rem;
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 0.3rem;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
    .route-info-item strong {
        color: var(--text-color);
        font-weight: 600;
    }
    .route-info-item span {
        color: var(--text-color);
    }
    /* Dark theme support */
    [data-theme="dark"] .route-info-horizontal {
        background-color: rgba(255, 255, 255, 0.05);
        border-color: rgba(255, 255, 255, 0.1);
    }
    [data-theme="dark"] .route-info-item {
        background-color: rgba(255, 255, 255, 0.1);
        border-color: rgba(255, 255, 255, 0.2);
    }
    /* Light theme support */
    [data-theme="light"] .route-info-horizontal {
        background-color: rgba(0, 0, 0, 0.05);
        border-color: rgba(0, 0, 0, 0.1);
    }
    [data-theme="light"] .route-info-item {
        background-color: rgba(0, 0, 0, 0.05);
        border-color: rgba(0, 0, 0, 0.1);
    }
</style>
""",
    unsafe_allow_html=True,
)

# Hong Kong coordinates
HK_CENTER = [22.3193, 114.1694]

# Cache file for route data
CACHE_FILE = "kmb_routes_cache.json"


@st.cache_data(ttl=3600)
def load_kmb_data():
    """Load KMB route and stop data"""
    try:
        api_manager = HKTransportAPIManager()
        routes = api_manager.get_all_routes()
        stops = api_manager.get_all_stops()
        return routes.get("KMB/LWB", pd.DataFrame()), stops.get(
            "KMB/LWB", pd.DataFrame()
        )
    except Exception as e:
        st.error(f"Error loading KMB data: {e}")
        return pd.DataFrame(), pd.DataFrame()


@st.cache_data(ttl=3600)
def get_osm_route_with_waypoints(stops_coords):
    """Get OSM route through multiple waypoints (bus stops) using OSRM"""
    if len(stops_coords) < 2:
        return None

    try:
        # Create coordinate string for OSRM with waypoints
        coords_str = ";".join([f"{lng},{lat}" for lat, lng in stops_coords])

        # Use OSRM Demo server for routing with waypoints
        url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"

        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "routes" in data and len(data["routes"]) > 0:
                geometry = data["routes"][0]["geometry"]
                if geometry and "coordinates" in geometry:
                    # Convert from [lng, lat] to [lat, lng] for folium
                    coordinates = [
                        [coord[1], coord[0]] for coord in geometry["coordinates"]
                    ]
                    return coordinates
    except Exception as e:
        # If OSM routing fails, return None to fall back to straight line
        pass
    return None


@st.cache_data(ttl=3600)
def get_osm_route_segments(stops_coords, max_waypoints=25):
    """Get OSM route through segments of waypoints for better routing"""
    if len(stops_coords) < 2:
        return []

    all_coordinates = []

    # Split into segments if too many stops (OSRM has limits)
    for i in range(0, len(stops_coords), max_waypoints - 1):
        segment_stops = stops_coords[i : i + max_waypoints]

        if len(segment_stops) < 2:
            continue

        segment_route = get_osm_route_with_waypoints(segment_stops)

        if segment_route:
            if i == 0:  # First segment
                all_coordinates.extend(segment_route)
            else:  # Subsequent segments, avoid duplication
                all_coordinates.extend(segment_route[1:])
        else:
            # Fallback to straight lines for this segment
            if i == 0:
                all_coordinates.extend(segment_stops)
            else:
                all_coordinates.extend(segment_stops[1:])

    return all_coordinates


def get_route_geometry(route_stops):
    """Get route geometry using OSM routing through all bus stops as waypoints"""
    if route_stops.empty:
        return []

    # Sort stops by sequence
    sorted_stops = route_stops.sort_values("sequence")

    if len(sorted_stops) < 2:
        return []

    # Get all stop coordinates in order
    stops_coords = []
    for idx, stop in sorted_stops.iterrows():
        if pd.notna(stop["lat"]) and pd.notna(stop["lng"]):
            stops_coords.append([stop["lat"], stop["lng"]])

    if len(stops_coords) < 2:
        return stops_coords

    # Create progress bar
    progress_bar = st.progress(0)
    progress_text = st.empty()

    # Update progress
    progress_text.text(f"🗺️ Getting bus route through {len(stops_coords)} stops...")
    progress_bar.progress(0.3)

    # Get OSM route through all waypoints
    all_coordinates = get_osm_route_segments(stops_coords)

    progress_bar.progress(0.8)
    progress_text.text(f"🗺️ Processing route geometry...")

    # If OSM routing fails, fall back to straight lines
    if not all_coordinates:
        all_coordinates = stops_coords
        progress_text.text(f"⚠️ Using direct path (OSM routing failed)")
    else:
        progress_text.text(f"✅ Route loaded with {len(all_coordinates)} path points")

    progress_bar.progress(1.0)

    # Clear progress indicators after a brief moment
    import time

    time.sleep(1)
    progress_bar.empty()
    progress_text.empty()

    return all_coordinates


def get_route_stops(route_id, direction=1, service_type=1):
    """Get stops for a specific route"""
    try:
        api_manager = HKTransportAPIManager()
        return api_manager.get_route_stops(route_id, direction, service_type)
    except Exception as e:
        st.error(f"Error loading route stops: {e}")
        return pd.DataFrame()


def create_route_map(route_stops, selected_stop_id=None):
    """Create map with route stops and OSM routing path"""
    # Create map centered on Hong Kong
    m = folium.Map(location=HK_CENTER, zoom_start=11, tiles="OpenStreetMap")

    if not route_stops.empty:
        # Get OSM route geometry (with progress bar)
        route_coords = get_route_geometry(route_stops)

        # Add route path using OSM waypoint routing
        if len(route_coords) > 1:
            folium.PolyLine(
                locations=route_coords,
                color="#1f77b4",
                weight=5,
                opacity=0.8,
                popup="Bus Route (OSM Waypoints)",
                tooltip="Actual Bus Route Through All Stops",
            ).add_to(m)

        # Also add a lighter straight-line path for reference
        stop_coords = []
        for idx, stop in route_stops.iterrows():
            if pd.notna(stop["lat"]) and pd.notna(stop["lng"]):
                stop_coords.append([stop["lat"], stop["lng"]])

        if len(stop_coords) > 1:
            folium.PolyLine(
                locations=stop_coords,
                color="lightblue",
                weight=2,
                opacity=0.4,
                popup="Direct Path",
                tooltip="Direct Line Between Stops",
                dashArray="5, 5",
            ).add_to(m)

        # Add stop markers
        for idx, stop in route_stops.iterrows():
            if pd.notna(stop["lat"]) and pd.notna(stop["lng"]):
                # Determine marker color
                if stop["stop_id"] == selected_stop_id:
                    marker_color = "red"
                    icon_color = "white"
                elif "depot" in stop.get("stop_name", "").lower():
                    marker_color = "green"
                    icon_color = "white"
                else:
                    marker_color = "blue"
                    icon_color = "white"

                # Create popup content
                popup_content = f"""
                <b>Stop {stop['sequence']}: {stop['stop_name']}</b><br>
                Stop ID: {stop['stop_id']}<br>
                Coordinates: {stop['lat']:.6f}, {stop['lng']:.6f}
                """

                folium.Marker(
                    location=[stop["lat"], stop["lng"]],
                    popup=folium.Popup(popup_content, max_width=300),
                    icon=folium.Icon(
                        color=marker_color,
                        icon_color=icon_color,
                        icon="bus",
                        prefix="fa",
                    ),
                ).add_to(m)

        # Auto-fit map to route bounds (use OSM route if available, otherwise stop coordinates)
        if route_coords:
            m.fit_bounds(route_coords)
        elif stop_coords:
            m.fit_bounds(stop_coords)

    return m


def main():
    """Main application function"""
    st.markdown(
        '<h1 class="main-header">🚌 Hong Kong KMB Route Map</h1>', unsafe_allow_html=True
    )

    # Load KMB data
    with st.spinner("Loading KMB data..."):
        routes_df, stops_df = load_kmb_data()

    # Sidebar for route selection
    st.sidebar.header("🚌 Route Selection")

    if not routes_df.empty:
        # Create route options
        route_options = []
        for idx, route in routes_df.iterrows():
            route_display = f"{route['route_id']} - {route.get('origin', 'N/A')} to {route.get('destination', 'N/A')}"
            route_options.append(
                (route_display, route["route_id"], 1, route.get("service_type", 1))
            )

        selected_route_display = st.sidebar.selectbox(
            "Select Route", ["None"] + [opt[0] for opt in route_options]
        )

        selected_route_id = None
        selected_direction = 1
        selected_service_type = 1
        route_stops = pd.DataFrame()

        if selected_route_display != "None":
            # Find selected route details
            for opt in route_options:
                if opt[0] == selected_route_display:
                    selected_route_id = opt[1]
                    selected_direction = opt[2] if opt[2] else 1
                    selected_service_type = opt[3] if opt[3] else 1
                    break

            # Load route stops
            if selected_route_id:
                with st.spinner("Loading route stops..."):
                    route_stops = get_route_stops(
                        selected_route_id, selected_direction, selected_service_type
                    )

                if not route_stops.empty:
                    # Stop selection
                    stop_options = [
                        f"Stop {row['sequence']}: {row['stop_name']}"
                        for idx, row in route_stops.iterrows()
                    ]
                    selected_stop_display = st.sidebar.selectbox(
                        "Select Stop (Optional)", ["None"] + stop_options
                    )

                    selected_stop_id = None
                    if selected_stop_display != "None":
                        stop_seq = int(
                            selected_stop_display.split(":")[0].replace("Stop ", "")
                        )
                        selected_stop_row = route_stops[
                            route_stops["sequence"] == stop_seq
                        ]
                        if not selected_stop_row.empty:
                            selected_stop_id = selected_stop_row.iloc[0]["stop_id"]
                else:
                    st.sidebar.warning("No stops found for this route")
    else:
        st.sidebar.error("No routes available")

    # Clear cache button
    if st.sidebar.button("🔄 Clear Cache & Refresh"):
        st.cache_data.clear()
        st.rerun()

    # Main content - Map only
    st.header("🗺️ Route Map")

    if not route_stops.empty:
        # Display route info - horizontal and theme-adaptive
        route_info = routes_df[routes_df["route_id"] == selected_route_id].iloc[0]

        with st.container():
            st.markdown(
                f"""
            <div class="route-info-horizontal">
                <div class="route-info-item">
                    <strong>🚌 Route:</strong><br/>
                    <span>{route_info['route_id']}</span>
                </div>
                <div class="route-info-item">
                    <strong>📍 From:</strong><br/>
                    <span>{route_info.get('origin', 'N/A')}</span>
                </div>
                <div class="route-info-item">
                    <strong>🎯 To:</strong><br/>
                    <span>{route_info.get('destination', 'N/A')}</span>
                </div>
                <div class="route-info-item">
                    <strong>🚏 Total Stops:</strong><br/>
                    <span>{len(route_stops)}</span>
                </div>
                <div class="route-info-item">
                    <strong>⚙️ Service Type:</strong><br/>
                    <span>{route_info.get('service_type', 'N/A')}</span>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        # Create and display map
        map_obj = create_route_map(route_stops, selected_stop_id)
        folium_static(map_obj, width=1200, height=600)

        # Display stops list
        st.subheader("📍 Route Stops")
        display_stops = route_stops[["sequence", "stop_name", "stop_id"]].copy()
        display_stops.columns = ["Sequence", "Stop Name", "Stop ID"]
        st.dataframe(display_stops, use_container_width=True)

    else:
        st.info("Please select a route to view the map and stops.")

        # Show default Hong Kong map
        default_map = folium.Map(
            location=HK_CENTER, zoom_start=11, tiles="OpenStreetMap"
        )
        folium_static(default_map, width=1200, height=600)


if __name__ == "__main__":
    main()
