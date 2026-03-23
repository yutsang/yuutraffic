"""
This is a boilerplate pipeline 'web_app'
generated using Kedro 0.19.14
"""

import logging
import os
import re
import sqlite3
import time
from datetime import datetime
from typing import Any, Optional

import folium
import pandas as pd
import requests
import streamlit as st
from kedro.config import OmegaConfigLoader

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for magic numbers
MIN_STOPS_FOR_ROUTE = 2
HTTP_OK = 200
ZOOM_VERY_SPREAD = 0.3
ZOOM_MODERATE_SPREAD = 0.2
ZOOM_SOME_SPREAD = 0.1
ZOOM_CLOSE = 0.05
ZOOM_VERY_CLOSE = 0.02

# Load configuration
conf_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "conf")
conf_loader = OmegaConfigLoader(conf_source=conf_path)
params = conf_loader["parameters"]

# Configuration constants
HK_CENTER = [params["map"]["center"]["lat"], params["map"]["center"]["lng"]]
DEFAULT_ZOOM = params["map"]["default_zoom"]
ROUTE_ZOOM = params["map"]["auto_zoom"]["route_zoom"]
STOP_ZOOM = params["map"]["auto_zoom"]["stop_zoom"]
DB_PATH = params["database"]["path"]
OSM_BASE_URL = params["api"]["osm_routing_url"]
MAX_WAYPOINTS = params["osm"]["max_waypoints"]
OSM_TIMEOUT = params["osm"]["timeout"]


def load_traffic_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load traffic route and stop data from database"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get all routes with enhanced route type detection
            routes_query = """
                SELECT DISTINCT
                    route_id,
                    route_name,
                    origin_en as origin,
                    destination_en as destination,
                    service_type,
                    company
                FROM routes
                ORDER BY route_id
            """
            routes_df = pd.read_sql_query(routes_query, conn)

            # Add route type classification
            routes_df["route_type"] = routes_df.apply(classify_route_type, axis=1)

            # Get all stops
            stops_query = """
                SELECT
                    stop_id,
                    stop_name_en as stop_name,
                    lat,
                    lng,
                    company
                FROM stops
                ORDER BY stop_id
            """
            stops_df = pd.read_sql_query(stops_query, conn)

        return routes_df, stops_df

    except Exception as e:
        st.error(f"Error loading traffic data: {e}")
        logger.error(f"Database error: {e}")
        return pd.DataFrame(), pd.DataFrame()


def _get_special_route_type(indicator: str) -> str:
    """Get route type based on indicator suffix"""
    route_type_map = {
        "X": "Express",
        "N": "Night",
        "P": "Peak",
        "A": "Airport",
        "E": "Airport",
        "S": "Special Service",
        "R": "Special Service",
    }
    return route_type_map.get(indicator, "Special")


def classify_route_type(route_row) -> str:
    """Classify route type based on route ID and destination"""
    route_id = str(route_row["route_id"]).upper()
    destination = str(route_row.get("destination", "")).upper()

    # Check for circular routes
    circular_indicators = params["route_types"]["circular"]
    if any(indicator in destination for indicator in circular_indicators):
        return "Circular"

    # Check for special route types
    special_indicators = params["route_types"]["special"]
    for indicator in special_indicators:
        if route_id.endswith(indicator):
            return _get_special_route_type(indicator)

    return "Regular"


def get_route_stops_with_directions(route_id: str) -> pd.DataFrame:
    """Get stops for a route with both directions"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            query = """
                SELECT
                    rs.route_id,
                    rs.stop_id,
                    s.stop_name_en as stop_name,
                    s.lat,
                    s.lng,
                    rs.sequence,
                    rs.direction,
                    rs.service_type,
                    s.company
                FROM route_stops rs
                JOIN stops s ON rs.stop_id = s.stop_id
                WHERE rs.route_id = ?
                ORDER BY rs.direction, rs.sequence
            """
            return pd.read_sql_query(query, conn, params=(route_id,))

    except Exception as e:
        logger.error(f"Error fetching route stops for {route_id}: {e}")
        return pd.DataFrame()


def get_route_directions_with_depots(route_id: str) -> list[dict[str, Any]]:
    """Get route directions with proper depot names (origin/destination)"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Get route information
            route_query = """
                SELECT origin_en, destination_en, route_type
                FROM routes
                WHERE route_id = ?
            """
            route_info = pd.read_sql_query(route_query, conn, params=(route_id,))

            if route_info.empty:
                return []

            route_data = route_info.iloc[0]
            origin = route_data["origin_en"]
            destination = route_data["destination_en"]
            route_type = route_data.get("route_type", "Regular")

            # Get available directions
            directions_query = """
                SELECT DISTINCT direction, COUNT(*) as stop_count
                FROM route_stops
                WHERE route_id = ?
                GROUP BY direction
                ORDER BY direction
            """
            directions_df = pd.read_sql_query(
                directions_query, conn, params=(route_id,)
            )

            directions = []
            for _, dir_row in directions_df.iterrows():
                direction = dir_row["direction"]
                stop_count = dir_row["stop_count"]

                if route_type == "Circular":
                    # Circular routes have same origin/destination
                    depot_name = f"{origin} (Circular)"
                    direction_name = "Circular"
                elif direction == 1:  # Outbound
                    depot_name = f"{origin} → {destination}"
                    direction_name = "Outbound"
                else:  # Inbound
                    depot_name = f"{destination} → {origin}"
                    direction_name = "Inbound"

                directions.append(
                    {
                        "direction": direction,
                        "name": direction_name,
                        "depot": depot_name,
                        "stops": stop_count,
                    }
                )

            return directions

    except Exception as e:
        logger.error(f"Error getting directions for {route_id}: {e}")
        return []


def natural_sort_key(route_id: str) -> tuple[int, str]:
    """Create a natural sort key for route IDs"""
    # Extract numeric and non-numeric parts
    match = re.match(r"(\d+)(.*)", route_id)
    if match:
        number = int(match.group(1))
        suffix = match.group(2)
        return (number, suffix)
    return (0, route_id)


def get_sorted_routes(routes_df: pd.DataFrame) -> pd.DataFrame:
    """Sort routes using natural sort order"""
    routes_df = routes_df.copy()
    routes_df["sort_key"] = routes_df["route_id"].apply(natural_sort_key)
    routes_df = routes_df.sort_values("sort_key")
    routes_df = routes_df.drop("sort_key", axis=1)
    return routes_df


def search_routes_with_directions(
    routes_df: pd.DataFrame, search_term: str
) -> list[dict[str, Any]]:
    """Search routes and return both directions with depot names"""
    if not search_term:
        return []

    # Filter routes based on search
    mask = (
        routes_df["route_id"].str.contains(search_term, case=False, na=False)
        | routes_df["origin"].str.contains(search_term, case=False, na=False)
        | routes_df["destination"].str.contains(search_term, case=False, na=False)
    )
    filtered_routes = routes_df[mask]

    results = []
    for _, route in filtered_routes.iterrows():
        route_id = route["route_id"]
        route_type = route["route_type"]

        # Get directions for this route
        directions = get_route_directions_with_depots(route_id)

        for direction_info in directions:
            results.append(
                {
                    "route_id": route_id,
                    "route_type": route_type,
                    "direction": direction_info["direction"],
                    "direction_name": direction_info["name"],
                    "depot_name": direction_info["depot"],
                    "stop_count": direction_info["stops"],
                    "display_text": f"{route_id} - {direction_info['depot']} ({direction_info['name']}, {direction_info['stops']} stops) [{route_type}]",
                }
            )

    return results


def get_osm_route_with_waypoints(
    stops_coords: list[tuple[float, float]], max_waypoints: int = MAX_WAYPOINTS
) -> list[list[float]]:
    """Get OSM route through waypoints with segmentation for large routes"""
    if len(stops_coords) < MIN_STOPS_FOR_ROUTE:
        return []

    all_coordinates = []

    # Split into segments if too many stops (OSRM has limits)
    for i in range(0, len(stops_coords), max_waypoints - 1):
        segment_stops = stops_coords[i : i + max_waypoints]

        if len(segment_stops) < MIN_STOPS_FOR_ROUTE:
            continue

        segment_route = get_single_osm_route(segment_stops)

        if segment_route:
            if i == 0:  # First segment
                all_coordinates.extend(segment_route)
            else:  # Subsequent segments, avoid duplication
                all_coordinates.extend(segment_route[1:])
        # Fallback to straight lines for this segment
        elif i == 0:
            all_coordinates.extend([[lat, lng] for lat, lng in segment_stops])
        else:
            all_coordinates.extend([[lat, lng] for lat, lng in segment_stops[1:]])

    return all_coordinates


def get_single_osm_route(
    stops_coords: list[tuple[float, float]]
) -> Optional[list[list[float]]]:
    """Get OSM route for a single segment"""
    try:
        # Create coordinate string for OSRM with waypoints
        coords_str = ";".join([f"{lng},{lat}" for lat, lng in stops_coords])

        # Use OSRM API for routing with waypoints
        url = f"{OSM_BASE_URL}/{coords_str}?overview=full&geometries=geojson"

        response = requests.get(url, timeout=OSM_TIMEOUT)
        if response.status_code == HTTP_OK:
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
        logger.warning(f"OSM routing failed: {e}")

    return None


def get_route_geometry_with_progress(
    route_stops: pd.DataFrame, direction: int
) -> list[list[float]]:
    """Get route geometry with progress tracking"""
    if route_stops.empty:
        return []

    # Filter by direction and sort by sequence
    direction_stops = route_stops[route_stops["direction"] == direction].sort_values(
        "sequence"
    )

    if len(direction_stops) < MIN_STOPS_FOR_ROUTE:
        return []

    # Get stop coordinates in order
    stops_coords = []
    for idx, stop in direction_stops.iterrows():
        if pd.notna(stop["lat"]) and pd.notna(stop["lng"]):
            stops_coords.append((stop["lat"], stop["lng"]))

    if len(stops_coords) < MIN_STOPS_FOR_ROUTE:
        return stops_coords

    # Progress tracking
    if params["ui"]["show_progress_bars"]:
        progress_bar = st.progress(0)
        progress_text = st.empty()

        # Update progress
        progress_text.text(f"🗺️ Getting route through {len(stops_coords)} stops...")
        progress_bar.progress(0.3)

    # Get OSM route through all waypoints
    all_coordinates = get_osm_route_with_waypoints(stops_coords)

    if params["ui"]["show_progress_bars"]:
        progress_bar.progress(0.8)
        progress_text.text("🗺️ Processing route geometry...")

    # If OSM routing fails, fall back to straight lines
    if not all_coordinates:
        all_coordinates = [[lat, lng] for lat, lng in stops_coords]
        if params["ui"]["show_progress_bars"]:
            progress_text.text("⚠️ Using direct path (OSM routing unavailable)")
    elif params["ui"]["show_progress_bars"]:
        progress_text.text(f"✅ Route loaded with {len(all_coordinates)} path points")

    if params["ui"]["show_progress_bars"]:
        progress_bar.progress(1.0)

        # Clear progress indicators
        time.sleep(1)
        progress_bar.empty()
        progress_text.empty()

    return all_coordinates


def _calculate_map_bounds(
    route_stops: pd.DataFrame, direction: int, selected_stop_id: Optional[str] = None
) -> tuple[float, float, int]:
    """Calculate map center and zoom level based on route stops"""
    if not route_stops.empty:
        direction_stops = route_stops[route_stops["direction"] == direction]
        if not direction_stops.empty:
            lats = direction_stops["lat"].dropna()
            lngs = direction_stops["lng"].dropna()

            if len(lats) > 0 and len(lngs) > 0:
                center_lat = lats.mean()
                center_lng = lngs.mean()
                lat_range = lats.max() - lats.min()
                lng_range = lngs.max() - lngs.min()
                max_range = max(lat_range, lng_range)

                # Determine zoom level based on spread
                if max_range > ZOOM_VERY_SPREAD:
                    zoom_level = 11
                elif max_range > ZOOM_MODERATE_SPREAD:
                    zoom_level = 12
                elif max_range > ZOOM_SOME_SPREAD:
                    zoom_level = 13
                elif max_range > ZOOM_CLOSE:
                    zoom_level = 14
                elif max_range > ZOOM_VERY_CLOSE:
                    zoom_level = 15
                else:
                    zoom_level = 16

                # Override for selected stop
                if selected_stop_id and params["map"]["auto_zoom"]["enabled"]:
                    zoom_level = min(zoom_level + 1, STOP_ZOOM)

                return center_lat, center_lng, zoom_level

    return HK_CENTER[0], HK_CENTER[1], DEFAULT_ZOOM


def _add_center_button(m: folium.Map) -> None:
    """Add center button to map"""
    center_button_html = f"""
    <div style="position: fixed;
                top: 10px; right: 10px; width: 150px; height: 40px;
                background-color: white; border: 2px solid #1f77b4;
                border-radius: 5px; z-index: 1000; font-size: 14px;
                display: flex; align-items: center; justify-content: center;
                cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.2);"
         onclick="map.setView([{HK_CENTER[0]}, {HK_CENTER[1]}], {DEFAULT_ZOOM});">
        🏠 Center Map
    </div>
    """
    m.get_root().html.add_child(folium.Element(center_button_html))


def _add_route_path(m: folium.Map, route_stops: pd.DataFrame, direction: int) -> None:
    """Add route path to map"""
    route_coords = get_route_geometry_with_progress(route_stops, direction)

    if len(route_coords) > 1:
        folium.PolyLine(
            locations=route_coords,
            color="#1f77b4",
            weight=5,
            opacity=0.8,
            popup=f"Bus Route Direction {direction} (OSM)",
            tooltip="Actual Bus Route Through All Stops",
        ).add_to(m)


def _add_stop_markers(
    m: folium.Map,
    route_stops: pd.DataFrame,
    direction: int,
    selected_stop_id: Optional[str] = None,
) -> None:
    """Add stop markers to map"""
    direction_stops = route_stops[route_stops["direction"] == direction].sort_values(
        "sequence"
    )

    for idx, stop in direction_stops.iterrows():
        if pd.notna(stop["lat"]) and pd.notna(stop["lng"]):
            if selected_stop_id and stop["stop_id"] == selected_stop_id:
                icon = folium.Icon(color="red", icon="star", prefix="fa")
                popup_text = f"🌟 SELECTED: {stop['stop_name']}<br/>Stop #{stop['sequence']}<br/>ID: {stop['stop_id']}"
            else:
                icon = folium.Icon(color="blue", icon="bus", prefix="fa")
                popup_text = f"🚏 {stop['stop_name']}<br/>Stop #{stop['sequence']}<br/>ID: {stop['stop_id']}"

            folium.Marker(
                location=[stop["lat"], stop["lng"]],
                popup=popup_text,
                tooltip=f"Stop {stop['sequence']}: {stop['stop_name']}",
                icon=icon,
            ).add_to(m)


def _add_reference_line(
    m: folium.Map, route_stops: pd.DataFrame, direction: int
) -> None:
    """Add reference line between stops"""
    direction_stops = route_stops[route_stops["direction"] == direction].sort_values(
        "sequence"
    )
    stop_coords = []

    for idx, stop in direction_stops.iterrows():
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


def create_enhanced_route_map(
    route_stops: pd.DataFrame,
    selected_stop_id: Optional[str] = None,
    direction: int = 1,
) -> folium.Map:
    """Create enhanced map with route stops, OSM routing, and center button"""
    center_lat, center_lng, zoom_level = _calculate_map_bounds(
        route_stops, direction, selected_stop_id
    )

    # Create map
    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=zoom_level,
        tiles=params["map"]["tiles"],
    )

    _add_center_button(m)

    if not route_stops.empty:
        _add_route_path(m, route_stops, direction)
        _add_stop_markers(m, route_stops, direction, selected_stop_id)
        _add_reference_line(m, route_stops, direction)

    return m


def format_route_type_badge(route_type: str) -> str:
    """Format route type as a colored badge"""
    type_colors = {
        "Regular": "#28a745",
        "Express": "#fd7e14",
        "Circular": "#6f42c1",
        "Night": "#212529",
        "Peak": "#dc3545",
        "Airport": "#17a2b8",
        "Special Service": "#ffc107",
        "Special": "#6c757d",
    }

    color = type_colors.get(route_type, "#6c757d")
    return f'<span style="background-color: {color}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 12px; font-weight: bold;">{route_type}</span>'


def get_first_run_status() -> bool:
    """Check if this is the first run"""
    status_file = "data/.first_run_complete"
    return not os.path.exists(status_file)


def mark_first_run_complete():
    """Mark first run as complete"""
    status_file = "data/.first_run_complete"
    os.makedirs(os.path.dirname(status_file), exist_ok=True)
    with open(status_file, "w") as f:
        f.write("First run completed")


def should_update_data() -> bool:
    """Check if data should be updated based on schedule"""
    if get_first_run_status():
        return True

    # Check daily update schedule
    if params["schedule"]["daily_update"]["enabled"]:
        now = datetime.now()
        update_time = datetime.strptime(
            params["schedule"]["daily_update"]["time"], "%H:%M"
        ).time()

        # Simple check - in production, would use proper scheduler
        return now.time() >= update_time

    return False
