"""
Traffic ETA - Production Application
Enhanced Hong Kong public transport route explorer with comprehensive features
"""

import logging
import os
import sys
import traceback

import streamlit as st
from streamlit_folium import folium_static

logging.basicConfig(level=logging.INFO, format="%(message)s")

# Add the current directory and parent directories to the path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.dirname(current_dir))
sys.path.insert(0, os.path.dirname(os.path.dirname(current_dir)))

# Direct import from the correct relative path
try:
    from pipelines.web_app.nodes import (
        create_enhanced_route_map,
        format_route_type_badge,
        get_first_run_status,
        get_route_stops_with_directions,
        get_sorted_routes,
        load_traffic_data,
        mark_first_run_complete,
        search_routes_with_directions,
        should_update_data,
    )
except ImportError as e:
    logging.error(f"Import error: {e}")
    logging.error(f"Current working directory: {os.getcwd()}")
    logging.error(f"Python path: {sys.path}")

    # Fallback: try direct file import
    import importlib.util

    nodes_path = os.path.join(current_dir, "pipelines", "web_app", "nodes.py")
    spec = importlib.util.spec_from_file_location("nodes", nodes_path)
    if spec is not None and spec.loader is not None:
        nodes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(nodes)

        # Extract the functions we need
        load_traffic_data = nodes.load_traffic_data
        get_route_stops_with_directions = nodes.get_route_stops_with_directions
        search_routes_with_directions = nodes.search_routes_with_directions
        get_sorted_routes = nodes.get_sorted_routes
        create_enhanced_route_map = nodes.create_enhanced_route_map
        format_route_type_badge = nodes.format_route_type_badge
        should_update_data = nodes.should_update_data
        mark_first_run_complete = nodes.mark_first_run_complete
        get_first_run_status = nodes.get_first_run_status
    else:
        raise ImportError(f"Could not load module from {nodes_path}")

# Page configuration
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

# Simplified and improved CSS
st.markdown(
    """
<style>
    /* CSS Variables for Theme Support */
    :root {
        --bg-primary: #ffffff;
        --bg-secondary: #f8f9fa;
        --bg-accent: #e3f2fd;
        --text-primary: #333333;
        --text-secondary: #666666;
        --text-muted: #6c757d;
        --border-color: #e0e0e0;
        --border-light: #e9ecef;
        --shadow: 0 2px 4px rgba(0,0,0,0.1);
        --blue: #007bff;
        --green: #28a745;
        --orange: #fd7e14;
        --red: #dc3545;
    }

    /* Dark theme variables - simplified */
    @media (prefers-color-scheme: dark) {
        :root {
            --bg-primary: #0e1117;
            --bg-secondary: #262730;
            --bg-accent: rgba(33, 150, 243, 0.1);
            --text-primary: #ffffff;
            --text-secondary: #cccccc;
            --text-muted: #aaaaaa;
            --border-color: rgba(255, 255, 255, 0.1);
            --border-light: rgba(255, 255, 255, 0.05);
            --shadow: 0 2px 4px rgba(0,0,0,0.3);
            --blue: #2196f3;
        }
    }

    /* Streamlit base layout fixes */
    .main .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        max-width: 100% !important;
    }

    /* Full height layout */
    html, body, .stApp {
        height: 100vh !important;
        overflow-x: hidden !important;
    }

    .main {
        height: calc(100vh - 3rem) !important;
        overflow-y: auto !important;
    }

    /* Remove default spacing that creates placeholders */
    .stMarkdown, .stColumns, .stColumn {
        margin-bottom: 0 !important;
    }

    /* Override Streamlit's default container styling for route stops */
    .stColumn:nth-child(2) .stMarkdown {
        margin-bottom: 8px !important;
        padding: 0 !important;
    }

    .stColumn:nth-child(2) div[data-testid="stMarkdownContainer"] {
        margin-bottom: 8px !important;
        padding: 0 !important;
    }

    /* Ensure columns fill available height */
    .stColumns {
        height: 100% !important;
    }

    .stColumn {
        height: 100% !important;
    }

    /* Statistics styling - simplified */
    .stats-container {
        background: var(--bg-secondary);
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        border: 1px solid var(--border-color);
    }

    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 1rem;
        margin-top: 1rem;
    }

    .stat-item {
        background: var(--bg-accent);
        padding: 1rem;
        border-radius: 6px;
        text-align: center;
        border: 1px solid var(--border-light);
        transition: transform 0.2s ease;
    }

    .stat-item:hover {
        transform: translateY(-2px);
    }

    .stat-number {
        font-size: 1.5rem;
        font-weight: bold;
        color: var(--blue);
        display: block;
    }

    .stat-label {
        font-size: 0.9rem;
        color: var(--text-muted);
        margin-top: 0.3rem;
    }

    /* Route information styling - smaller font size */
    .route-info-container {
        background: var(--bg-secondary);
        padding: 0.8rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        border: 1px solid var(--border-color);
        transition: all 0.3s ease;
    }

    /* Compact button styling for reverse button */
    .stButton > button {
        padding: 0.3rem 0.8rem !important;
        font-size: 0.8rem !important;
        height: auto !important;
        min-height: 2rem !important;
    }

    /* Aggressive fix for route information columns - force minimal height and no background */
    .route-info-section .stColumns {
        gap: 0.5rem !important;
    }

    .route-info-section .stColumn {
        padding: 0 !important;
        margin: 0 !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        min-height: auto !important;
        height: auto !important;
    }

    .route-info-section .stColumn > div {
        padding: 0 !important;
        margin: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
    }

    .route-info-section .stColumn .element-container {
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
    }

    .route-info-section .stColumn .stMarkdown {
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
    }

    .route-info-section .stColumn div[data-testid="stMarkdownContainer"] {
        background: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
        min-height: auto !important;
        height: auto !important;
    }

    .route-info-section .stColumn .stButton {
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
    }

    .route-info-section .stColumn .stButton > div {
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
    }

    .route-info-container:hover {
        border-color: var(--blue);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }

    .route-info-row {
        display: flex;
        align-items: center;
        gap: 0.8rem;
        flex-wrap: wrap;
    }

    .route-info-left {
        display: flex;
        align-items: center;
        gap: 0.8rem;
        flex: 1;
        flex-wrap: wrap;
    }

    .route-info-item {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        margin-bottom: 0.4rem;
    }

    .route-icon {
        font-size: 0.9rem;
        color: var(--text-secondary);
        width: 20px;
        text-align: center;
    }

    .route-detail {
        background: var(--bg-accent);
        padding: 0.4rem 0.8rem;
        border-radius: 16px;
        border: 1px solid var(--border-color);
        font-size: 0.8rem;
        color: var(--text-primary);
        white-space: nowrap;
        min-width: 100px;
        text-align: center;
    }

    .route-detail.route-number {
        border-color: var(--blue);
        color: var(--blue);
        font-weight: bold;
    }

    .route-detail.route-type {
        border-color: var(--green);
        color: var(--green);
    }

    .route-detail.route-origin {
        border-color: var(--orange);
        color: var(--orange);
    }

    .route-detail.route-destination {
        border-color: var(--red);
        color: var(--red);
    }

    .route-detail.route-direction {
        border-color: var(--text-secondary);
        color: var(--text-secondary);
    }

    .route-reverse-btn {
        background: var(--blue);
        color: white;
        border: none;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s ease;
        white-space: nowrap;
        font-size: 0.9rem;
    }

    .route-reverse-btn:hover {
        background: var(--text-secondary);
        transform: translateY(-1px);
    }

    .route-reverse-btn:disabled {
        background: var(--text-muted);
        cursor: not-allowed;
        transform: none;
    }

    /* Main content styling */
    .main-content {
        max-width: 100%;
        padding: 0;
        height: 100%;
    }

    .map-stops-container {
        display: flex;
        gap: 1rem;
        height: 650px;
        min-height: 600px;
        margin: 1rem 0;
        align-items: flex-start;
    }

    .map-column {
        flex: 2;
        min-width: 0;
        height: 100%;
    }

    .stops-column {
        flex: 1;
        min-width: 300px;
        height: 600px;
        max-height: 600px;
        overflow: hidden;
    }

    /* Route stops container styling - match map height */
    .stops-container {
        height: 100%;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    /* Scrollbar styling for route stops column */
    .stColumn:nth-child(2)::-webkit-scrollbar {
        width: 8px;
    }

    .stColumn:nth-child(2)::-webkit-scrollbar-track {
        background: #f8f9fa;
        border-radius: 4px;
    }

    .stColumn:nth-child(2)::-webkit-scrollbar-thumb {
        background: #007bff;
        border-radius: 4px;
    }

    .stColumn:nth-child(2)::-webkit-scrollbar-thumb:hover {
        background: #0056b3;
    }

    .stops-header {
        padding: 1rem;
        border-bottom: 1px solid var(--border-color);
        background: var(--bg-primary);
    }

    .stops-list {
        flex: 1;
        overflow-y: auto;
        padding: 1rem;
    }

    .stops-list::-webkit-scrollbar {
        width: 8px;
    }

    .stops-list::-webkit-scrollbar-track {
        background: var(--bg-secondary);
        border-radius: 4px;
    }

    .stops-list::-webkit-scrollbar-thumb {
        background: var(--blue);
        border-radius: 4px;
    }

    .stops-list::-webkit-scrollbar-thumb:hover {
        background: var(--text-secondary);
    }

    .stop-item {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.75rem;
        margin-bottom: 0.5rem;
        background: var(--bg-primary);
        border-radius: 8px;
        border: 1px solid var(--border-light);
        transition: all 0.2s ease;
        cursor: pointer;
    }

    .stop-item:hover {
        background: var(--bg-accent);
        border-color: var(--blue);
        transform: translateX(4px);
    }

    .stop-number {
        background: var(--blue);
        color: white;
        padding: 0.4rem 0.6rem;
        border-radius: 50%;
        font-size: 0.8rem;
        font-weight: bold;
        min-width: 30px;
        height: 30px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }

    .stop-name {
        font-size: 0.9rem;
        flex: 1;
        color: var(--text-primary);
        line-height: 1.4;
    }

    .stop-name strong {
        color: var(--blue);
        display: block;
        margin-bottom: 0.2rem;
    }

    .stop-name small {
        color: var(--text-secondary);
        font-size: 0.8rem;
    }

    .welcome-container {
        text-align: center;
        padding: 3rem 2rem;
        background: var(--bg-secondary);
        border-radius: 12px;
        border: 1px solid var(--border-color);
        margin: 2rem 0;
        max-width: 600px;
        margin-left: auto;
        margin-right: auto;
    }

    .welcome-icon {
        font-size: 4rem;
        margin-bottom: 1rem;
        color: var(--blue);
        animation: bounce 2s infinite;
    }

    @keyframes bounce {
        0%, 20%, 50%, 80%, 100% {
            transform: translateY(0);
        }
        40% {
            transform: translateY(-10px);
        }
        60% {
            transform: translateY(-5px);
        }
    }

    .welcome-container h2 {
        color: var(--text-primary);
        margin-bottom: 1rem;
        font-size: 2rem;
    }

    .welcome-container p {
        color: var(--text-secondary);
        line-height: 1.8;
        margin-bottom: 1rem;
        font-size: 1.1rem;
    }

    /* Button styling improvements */
    .stButton > button {
        border-radius: 8px !important;
        border: 1px solid var(--border-color) !important;
        transition: all 0.2s ease !important;
        font-weight: 500 !important;
    }

    .stButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1) !important;
    }

    .stButton > button[kind="primary"] {
        background: var(--blue) !important;
        color: white !important;
        border-color: var(--blue) !important;
    }

    .stButton > button[kind="primary"]:hover {
        background: var(--blue) !important;
        filter: brightness(1.1) !important;
    }

    /* Map container styling - increased height */
    .map-container {
        height: 100%;
        border-radius: 8px;
        border: 1px solid var(--border-color);
        overflow: hidden;
        background: var(--bg-secondary);
    }

    .map-container iframe {
        width: 100% !important;
        height: 100% !important;
        border: none !important;
        display: block !important;
    }

    /* Fix for folium map display */
    .stApp .element-container iframe {
        width: 100% !important;
        height: 100% !important;
        min-height: 500px !important;
    }

    /* Responsive design improvements */
    @media (max-width: 1200px) {
        .route-info-row {
            flex-wrap: wrap;
        }

        .route-info-left {
            flex-wrap: wrap;
        }

        .map-stops-container {
            height: calc(100vh - 200px);
            min-height: 500px;
        }
    }

    @media (max-width: 768px) {
        .stats-grid {
            grid-template-columns: 1fr;
        }

        .route-info-row {
            flex-direction: column;
            gap: 0.5rem;
        }

        .route-info-left {
            flex-direction: column;
            align-items: flex-start;
        }

        .map-stops-container {
            flex-direction: column;
            height: calc(100vh - 150px);
            min-height: 700px;
        }

        .map-container {
            height: 60%;
            min-height: 350px;
        }

        .stops-container {
            height: 40%;
            min-height: 350px;
        }

        .stops-column {
            min-width: unset;
        }

        .welcome-container {
            padding: 2rem 1rem;
        }

        .welcome-container h2 {
            font-size: 1.5rem;
        }

        .welcome-container p {
            font-size: 1rem;
        }
    }

    @media (max-width: 480px) {
        .route-detail {
            min-width: 80px;
            font-size: 0.7rem;
        }

        .stop-item {
            padding: 0.5rem;
        }

        .stop-number {
            min-width: 24px;
            height: 24px;
            font-size: 0.7rem;
        }

        .stop-name {
            font-size: 0.8rem;
        }
    }
</style>
""",
    unsafe_allow_html=True,
)


# Check for first run and data updates
@st.cache_data(ttl=300)
def initialize_app():
    """Initialize the application with cached data loading."""
    try:
        # Load route and stop data (returns tuple)
        routes_df, stops_df = load_traffic_data()
        return routes_df, stops_df
    except Exception as e:
        st.error(f"Error initializing app: {str(e)}")
        return None, None


@st.cache_data(ttl=300)
def get_cached_route_stops(route_id):
    """Get route stops with caching."""
    return get_route_stops_with_directions(route_id)


@st.cache_data(ttl=300)
def get_cached_route_options(routes_df):
    """Create cached route options from routes dataframe."""
    return create_route_options(routes_df)


# Create route options for the dropdown
def create_route_options(routes_df):
    """Create formatted route options for the selectbox."""
    options = []
    for _, route in routes_df.iterrows():
        # Handle different column names
        try:
            origin = route["origin"]
            destination = route["destination"]
        except KeyError:
            origin = route["origin_en"]
            destination = route["destination_en"]

        route_type = route.get("route_type", "Regular")

        option = {
            "text": f"{route['route_id']} - {origin} → {destination} [{route_type}]",
            "route_id": route["route_id"],
            "origin": origin,
            "destination": destination,
            "route_type": route_type,
        }
        options.append(option)

    return options


# Add this helper function near the top of the file:
def split_name_for_box(name, max_len=25):
    if len(name) <= max_len:
        return name
    mid = len(name) // 2
    split_at = name.rfind(" ", 0, mid + 5)
    if split_at == -1:
        split_at = mid
    return name[:split_at] + "<br>" + name[split_at + 1 :]


def _initialize_session_state():
    """Initialize session state variables"""
    if "selected_route" not in st.session_state:
        st.session_state.selected_route = None
    if "selected_direction" not in st.session_state:
        st.session_state.selected_direction = None


def _setup_header():
    """Setup application header"""
    st.title("🗺️ Hong Kong Public Transport Explorer")
    st.header("🔍 Search Routes")


def _handle_route_selection(route_options):
    """Handle route selection from dropdown"""
    option_texts = ["Select a route and direction..."] + [
        opt["text"] for opt in route_options
    ]

    selected_option = st.selectbox(
        "🚌 Choose Route & Direction",
        option_texts,
        help="Type to search or select from dropdown",
    )

    if selected_option == "Select a route and direction...":
        return None

    # Find the selected route data
    for opt in route_options:
        if opt["text"] == selected_option:
            return opt

    return None


def _handle_direction_logic(route_stops, selected_route_data):
    """Handle direction selection and validation logic"""
    directions = route_stops["direction"].unique()
    route_id = selected_route_data["route_id"]

    # Reset direction if switching routes or if current direction doesn't exist
    if (
        st.session_state.get("selected_route") != route_id
        or st.session_state.get("selected_direction") not in directions
    ):
        st.session_state.selected_direction = directions[0]

    # Get current direction (ensure it's valid and is an integer)
    current_direction = st.session_state.get("selected_direction", directions[0])

    # Ensure current direction exists in available directions and is an integer
    if current_direction not in directions:
        current_direction = directions[0]
        st.session_state.selected_direction = current_direction

    # Ensure it's an integer
    try:
        current_direction = int(current_direction)
    except (ValueError, TypeError):
        current_direction = int(directions[0]) if len(directions) > 0 else 1
        st.session_state.selected_direction = current_direction

    return current_direction, directions


def _show_debug_info(current_direction, directions, route_stops):
    """Show debug information in development mode"""
    DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
    if DEBUG_MODE:
        with st.expander("Debug Information", expanded=False):
            st.write(
                f"DEBUG: Current direction: {current_direction} (type: {type(current_direction)})"
            )
            st.write(f"DEBUG: Available directions: {list(directions)}")
            st.write(f"DEBUG: Direction stops count: {len(route_stops)}")
            st.write(f"DEBUG: Total directions: {len(directions)}")


def _get_route_endpoints(direction_stops, selected_route_data):
    """Get origin and destination for current direction"""
    if not direction_stops.empty:
        first_stop = direction_stops.iloc[0]["stop_name"]
        last_stop = direction_stops.iloc[-1]["stop_name"]
    else:
        first_stop = selected_route_data["origin"]
        last_stop = selected_route_data["destination"]

    return first_stop, last_stop


def _display_route_info(selected_route_data, first_stop, last_stop, current_direction):
    """Display route information"""
    st.subheader("Route Information")

    route_info_html = f"""
    <div style="display: flex; gap: 0.5rem; align-items: stretch; margin-bottom: 1rem;">
        <div style="flex: 1; text-align: center; padding: 0.3rem; background: var(--bg-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
            <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 0.1rem;">🚌 Route</div>
            <div style="font-size: 0.9rem; font-weight: bold; color: var(--blue);">{selected_route_data['route_id']}</div>
        </div>
        <div style="flex: 1; text-align: center; padding: 0.3rem; background: var(--bg-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
            <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 0.1rem;">🏷️ Type</div>
            <div style="font-size: 0.8rem; font-weight: bold; color: var(--green);">{selected_route_data['route_type']}</div>
        </div>
        <div style="flex: 2; text-align: center; padding: 0.3rem; background: var(--bg-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
            <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 0.1rem;">📍 From</div>
            <div style="font-size: 0.75rem; font-weight: bold; color: var(--orange);">{split_name_for_box(first_stop)}</div>
        </div>
        <div style="flex: 2; text-align: center; padding: 0.3rem; background: var(--bg-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
            <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 0.1rem;">🎯 To</div>
            <div style="font-size: 0.75rem; font-weight: bold; color: var(--red);">{split_name_for_box(last_stop)}</div>
        </div>
        <div style="flex: 1; text-align: center; padding: 0.3rem; background: var(--bg-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
            <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 0.1rem;">🧭 Direction</div>
            <div style="font-size: 0.9rem; font-weight: bold; color: var(--text-secondary);">{str(current_direction)}</div>
        </div>
    </div>
    """
    st.markdown(route_info_html, unsafe_allow_html=True)


def _render_css_and_buttons(directions, current_direction):
    st.markdown(
        """
    <style>
    /* Ultra-aggressive targeting for button containers */
    .button-row .stColumns {
        gap: 0.5rem !important;
        background: transparent !important;
    }
    .button-row .stColumn {
        padding: 0 !important;
        margin: 0 !important;
        background: transparent !important;
        border: none !important;
        min-height: auto !important;
        height: auto !important;
        box-shadow: none !important;
    }
    .button-row .stColumn > div {
        padding: 0 !important;
        margin: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
        box-shadow: none !important;
    }
    .button-row .stColumn .element-container {
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
        box-shadow: none !important;
    }
    .button-row .stColumn .stButton {
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
        box-shadow: none !important;
    }
    .button-row .stColumn .stButton > div {
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        min-height: auto !important;
        height: auto !important;
        box-shadow: none !important;
    }
    .button-row .stButton > button {
        margin: 0 !important;
        height: 2.5rem !important;
        min-height: 2.5rem !important;
        padding: 0.5rem !important;
        font-size: 0.9rem !important;
    }
    .button-row div[data-testid] {
        background: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
        box-shadow: none !important;
    }
    .button-row * {
        background-color: transparent !important;
    }
    .button-row button {
        background-color: #dc3545 !important;
    }
    .button-row button:disabled {
        background-color: #6c757d !important;
    }
    .button-row button:not(:disabled):not(.btn-outline) {
        background-color: #dc3545 !important;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="button-row">', unsafe_allow_html=True)
    col_search, col_reverse = st.columns([4, 1])
    with col_search:
        if st.button(
            "🔍 Search Other Routes",
            key="search_other_routes",
            help="Click to search for other routes",
            use_container_width=True,
        ):
            st.session_state.selected_route = None
            st.session_state.selected_direction = None
            st.rerun()
    with col_reverse:
        if len(directions) > 1:
            if st.button(
                "🔄 REVERSE",
                key="reverse_direction_button",
                help="Reverse route direction",
                use_container_width=True,
                type="primary",
            ):
                other_directions = [d for d in directions if d != current_direction]
                if other_directions:
                    st.session_state.selected_direction = other_directions[0]
                    st.rerun()
        else:
            st.button(
                f"🧭 Dir {current_direction}",
                key="direction_display_button",
                help="Only one direction available",
                use_container_width=True,
                disabled=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)
    st.divider()


def _render_map_and_stops(direction_stops, current_direction):
    col1, col2 = st.columns([3, 1], gap="medium")
    with col1:
        st.subheader("🗺️ Route Map")
        try:
            with st.spinner("Loading route map..."):
                map_obj = create_enhanced_route_map(
                    direction_stops,
                    st.session_state.get("selected_stop_id"),
                    current_direction,
                )
                folium_static(map_obj, width=1200, height=600)
        except Exception as e:
            st.error(f"❌ Error creating map: {str(e)}")
            st.info("💡 Try refreshing the page or selecting a different route.")
            if os.getenv("DEBUG_MODE", "false").lower() == "true":
                st.write(f"Debug info: direction_stops shape: {direction_stops.shape}")
                st.write(f"Debug info: current_direction: {current_direction}")
                st.text(traceback.format_exc())
    with col2:
        st.subheader("🚏 Route Stops")
        if not direction_stops.empty:
            stops_html = "<div style='height:600px; overflow-y:auto; border:1px solid #e0e0e0; border-radius:8px; background:var(--bg-secondary); padding:8px;'>"
            for idx, stop in enumerate(direction_stops.itertuples(), 1):
                stops_html += (
                    f"<div style='display:flex; align-items:center; gap:0.75rem; "
                    f"padding:0.5rem 0.75rem; border-bottom:1px solid #444; "
                    f"background:var(--bg-primary); font-size:1rem; color:var(--text-primary);'>"
                    f"<span style='background:#2196f3; color:white; border-radius:50%; "
                    f"width:28px; height:28px; display:flex; align-items:center; justify-content:center; font-weight:bold;'>"
                    f"{idx}</span>"
                    f"<span style='flex:1;'>{stop.stop_name}</span>"
                    f"<span style='color:#888; font-size:0.85em;'>ID: {stop.stop_id}</span>"
                    f"</div>"
                )
            stops_html += "</div>"
            st.markdown(stops_html, unsafe_allow_html=True)
        else:
            st.info("⚠️ No stops found for this route.")


def _render_welcome_message():
    st.markdown(
        """
    <div class="welcome-container">
        <div class="welcome-icon">🚌</div>
        <h2>Welcome to Hong Kong Transport Explorer!</h2>
        <p>Select a route from the dropdown above to view its interactive map, route information, and stop details.</p>
        <p><strong>💡 Pro tip:</strong> You can type in the dropdown to quickly find routes!</p>
    </div>
    """,
        unsafe_allow_html=True,
    )


def _render_key_statistics(routes_df, stops_df):
    st.divider()
    st.header("📊 Key Statistics")
    try:
        all_destinations = set(routes_df["destination"].dropna().unique()) | set(
            routes_df["origin"].dropna().unique()
        )
    except KeyError:
        all_destinations = set(routes_df["destination_en"].dropna().unique()) | set(
            routes_df["origin_en"].dropna().unique()
        )
    total_routes = len(routes_df)
    total_stops = len(stops_df) if stops_df is not None and not stops_df.empty else 0
    total_destinations = len(all_destinations)
    st.markdown(
        f"""
    <div class="stats-container">
        <div class="stats-grid">
            <div class="stat-item">
                <div class="stat-number">{total_routes}</div>
                <div class="stat-label">Routes</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">{total_stops}</div>
                <div class="stat-label">Stops</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">{total_destinations}</div>
                <div class="stat-label">Destinations</div>
            </div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def main():
    try:
        with st.spinner("Loading transport data..."):
            routes_df, stops_df = initialize_app()
        if routes_df is None or routes_df.empty:
            st.error("❌ No route data available. Please check your data connection.")
            return
    except Exception as e:
        st.error(f"❌ Error loading data: {str(e)}")
        return
    _initialize_session_state()
    _setup_header()
    route_options = get_cached_route_options(routes_df)
    selected_route_data = _handle_route_selection(route_options)
    if selected_route_data:
        route_id = selected_route_data["route_id"]
        st.session_state.selected_route = route_id
        with st.spinner("Loading route details..."):
            route_stops = get_cached_route_stops(route_id)
        if not route_stops.empty:
            current_direction, directions = _handle_direction_logic(
                route_stops, selected_route_data
            )
            _show_debug_info(current_direction, directions, route_stops)
            direction_stops = route_stops[
                route_stops["direction"] == current_direction
            ].sort_values("sequence")
            first_stop, last_stop = _get_route_endpoints(
                direction_stops, selected_route_data
            )
            _display_route_info(
                selected_route_data, first_stop, last_stop, current_direction
            )
            _render_css_and_buttons(directions, current_direction)
            if not direction_stops.empty:
                _render_map_and_stops(direction_stops, current_direction)
            else:
                st.info("⚠️ No stop data available for this route")
        else:
            st.warning("⚠️ No stop data available for this route")
    else:
        _render_welcome_message()
    _render_key_statistics(routes_df, stops_df)


if __name__ == "__main__":
    main()
# touch for CI
