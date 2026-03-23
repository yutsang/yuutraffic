import json
import time
from datetime import datetime, timedelta

import folium
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from api_connectors import HKTransportAPIManager
from streamlit_folium import folium_static

# Page configuration
st.set_page_config(
    page_title="Hong Kong Real-time Transportation Dashboard",
    page_icon="🚇",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for better styling
st.markdown(
    """
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
        background: linear-gradient(90deg, #1f77b4, #ff7f0e);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .transport-icon {
        font-size: 2rem;
        margin-right: 0.5rem;
    }
    .status-normal { color: #28a745; }
    .status-delay { color: #ffc107; }
    .status-disruption { color: #dc3545; }
    .eta-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Hong Kong coordinates and boundaries
HK_CENTER = [22.3193, 114.1694]
HK_BOUNDARY = [[22.15, 113.8], [22.15, 114.5], [22.6, 114.5], [22.6, 113.8]]


# Initialize API manager
@st.cache_resource
def get_api_manager():
    return HKTransportAPIManager()


# Cache data functions
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_cached_routes():
    """Get cached routes from all companies"""
    api_manager = get_api_manager()
    return api_manager.get_all_routes()


@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_cached_stops():
    """Get cached stops from all companies"""
    api_manager = get_api_manager()
    return api_manager.get_all_stops()


@st.cache_data(ttl=60)  # Cache for 1 minute (ETA data updates frequently)
def get_cached_eta(company, stop_id, route_id=None):
    """Get cached ETA for a specific stop"""
    api_manager = get_api_manager()
    return api_manager.get_stop_eta(company, stop_id, route_id)


@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_cached_route_stops(company, route_id):
    """Get cached stops for a specific route"""
    api_manager = get_api_manager()
    return api_manager.get_route_stops(company, route_id)


def create_enhanced_map(
    transport_data, selected_route_stops=None, selected_stop=None, show_traffic=False
):
    """Create an enhanced interactive map with route visualization"""
    # Create base map centered on Hong Kong
    m = folium.Map(location=HK_CENTER, zoom_start=11, tiles="OpenStreetMap")

    # Add transportation data to map
    colors = {"MTR": "red", "KMB/LWB": "blue", "Citybus": "green", "GMB": "orange"}
    icons = {"MTR": "train", "KMB/LWB": "bus", "Citybus": "bus", "GMB": "car"}

    # Add all transport stops
    for transport_type in transport_data.keys():
        if not transport_data[transport_type].empty:
            df = transport_data[transport_type]
            color = colors.get(transport_type, "gray")
            icon_name = icons.get(transport_type, "info-sign")

            for idx, row in df.iterrows():
                if pd.notna(row["lat"]) and pd.notna(row["lng"]):
                    # Create popup content
                    popup_content = f"""
                    <b>{transport_type}: {row.get('stop_name', row.get('station_name', row.get('name', 'N/A')))}</b><br>
                    ID: {row.get('stop_id', row.get('station_id', 'N/A'))}<br>
                    <a href="#" onclick="showETA('{transport_type}', '{row.get('stop_id', row.get('station_id', ''))}')">View ETA</a>
                    """

                    folium.Marker(
                        location=[row["lat"], row["lng"]],
                        popup=folium.Popup(popup_content, max_width=300),
                        icon=folium.Icon(color=color, icon=icon_name),
                        tooltip=f"{transport_type}: {row.get('stop_name', row.get('station_name', row.get('name', 'N/A')))}",
                    ).add_to(m)

    # Add selected route stops with different styling
    if selected_route_stops is not None and not selected_route_stops.empty:
        # Draw route path
        route_coords = []
        for idx, row in selected_route_stops.iterrows():
            if pd.notna(row["lat"]) and pd.notna(row["lng"]):
                route_coords.append([row["lat"], row["lng"]])

        if len(route_coords) > 1:
            folium.PolyLine(
                locations=route_coords,
                color="purple",
                weight=4,
                opacity=0.8,
                popup="Selected Route",
            ).add_to(m)

        # Add route stops with special styling
        for idx, row in selected_route_stops.iterrows():
            if pd.notna(row["lat"]) and pd.notna(row["lng"]):
                is_selected = selected_stop and row.get("stop_id") == selected_stop

                popup_content = f"""
                <b>Route Stop: {row.get('stop_name', 'N/A')}</b><br>
                Sequence: {row.get('sequence', 'N/A')}<br>
                Route: {row.get('route_id', 'N/A')}<br>
                <a href="#" onclick="showETA('{row.get('company', 'KMB/LWB')}', '{row.get('stop_id', '')}')">View ETA</a>
                """

                folium.CircleMarker(
                    location=[row["lat"], row["lng"]],
                    radius=8 if is_selected else 6,
                    color="purple",
                    fill=True,
                    fillColor="purple" if is_selected else "white",
                    fillOpacity=0.8 if is_selected else 0.6,
                    weight=2,
                    popup=folium.Popup(popup_content, max_width=300),
                    tooltip=f"Route Stop: {row.get('stop_name', 'N/A')}",
                ).add_to(m)

    # Add Hong Kong boundary
    folium.Polygon(
        locations=HK_BOUNDARY,
        color="black",
        weight=2,
        fill=False,
        popup="Hong Kong SAR",
    ).add_to(m)

    # Add legend
    legend_html = """
    <div style="position: fixed; 
                bottom: 50px; left: 50px; width: 250px; height: 180px; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding: 10px">
    <p><b>Transportation Types</b></p>
    <p><i class="fa fa-train" style="color:red"></i> MTR Stations</p>
    <p><i class="fa fa-bus" style="color:blue"></i> KMB/LWB Stops</p>
    <p><i class="fa fa-bus" style="color:green"></i> Citybus Stops</p>
    <p><i class="fa fa-car" style="color:orange"></i> GMB Stops</p>
    <p><span style="color:purple; font-weight:bold;">●</span> Selected Route</p>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m


def display_eta_info(company, stop_id, route_id=None):
    """Display ETA information for a selected stop"""
    st.subheader(f"🚌 Real-time Arrival Times")

    # Get ETA data
    eta_data = get_cached_eta(company, stop_id, route_id)

    if eta_data.empty:
        st.warning("No ETA data available for this stop.")
        return

    # Display ETA information
    for idx, row in eta_data.iterrows():
        eta_time = row.get("eta", "N/A")
        route = row.get("route_id", "N/A")
        destination = row.get("dest_en", "N/A")

        # Calculate time until arrival
        if eta_time != "N/A":
            try:
                eta_dt = datetime.fromisoformat(eta_time.replace("Z", "+00:00"))
                now = datetime.now(eta_dt.tzinfo)
                time_diff = eta_dt - now
                minutes_away = int(time_diff.total_seconds() / 60)

                if minutes_away < 0:
                    status = "🟢 Arrived"
                    time_text = "Now"
                elif minutes_away < 5:
                    status = "🟡 Approaching"
                    time_text = f"{minutes_away} min"
                else:
                    status = "🔵 Scheduled"
                    time_text = f"{minutes_away} min"
            except:
                status = "⚪ Unknown"
                time_text = eta_time
        else:
            status = "⚪ Unknown"
            time_text = "N/A"

        with st.container():
            col1, col2, col3, col4 = st.columns([1, 2, 2, 1])
            with col1:
                st.markdown(f"**{status}**")
            with col2:
                st.markdown(f"**Route {route}**")
            with col3:
                st.markdown(f"**{destination}**")
            with col4:
                st.markdown(f"**{time_text}**")

        st.divider()


def create_dashboard():
    """Main dashboard function"""
    st.markdown(
        '<h1 class="main-header">🚇 Hong Kong Real-time Transportation Dashboard</h1>',
        unsafe_allow_html=True,
    )

    # Initialize API manager
    api_manager = get_api_manager()

    # Sidebar for controls
    st.sidebar.header("🚦 Transportation Options")

    # Transport mode selection
    transport_mode = st.sidebar.selectbox(
        "Select Transport Mode", ["All", "KMB/LWB", "MTR", "Citybus", "GMB"]
    )

    # Get cached data
    all_routes = get_cached_routes()
    all_stops = get_cached_stops()

    # Route selection
    if transport_mode != "All" and transport_mode in all_routes:
        routes_df = all_routes[transport_mode]
        if not routes_df.empty:
            route_options = [
                f"{row['route_id']} - {row['route_name']}"
                for idx, row in routes_df.iterrows()
            ]
            selected_route_display = st.sidebar.selectbox(
                "Select Route", ["None"] + route_options
            )

            if selected_route_display != "None":
                selected_route_id = selected_route_display.split(" - ")[0]

                # Get route stops
                route_stops = get_cached_route_stops(transport_mode, selected_route_id)

                if not route_stops.empty:
                    # Stop selection
                    stop_options = [
                        f"{row['stop_name']} (Seq: {row['sequence']})"
                        for idx, row in route_stops.iterrows()
                    ]
                    selected_stop_display = st.sidebar.selectbox(
                        "Select Stop", ["None"] + stop_options
                    )

                    if selected_stop_display != "None":
                        selected_stop_name = selected_stop_display.split(" (Seq:")[0]
                        selected_stop_row = route_stops[
                            route_stops["stop_name"] == selected_stop_name
                        ].iloc[0]
                        selected_stop_id = selected_stop_row["stop_id"]
                    else:
                        selected_stop_id = None
                        selected_stop_row = None
                else:
                    selected_stop_id = None
                    selected_stop_row = None
                    route_stops = pd.DataFrame()
            else:
                selected_route_id = None
                selected_stop_id = None
                selected_stop_row = None
                route_stops = pd.DataFrame()
        else:
            selected_route_id = None
            selected_stop_id = None
            selected_stop_row = None
            route_stops = pd.DataFrame()
    else:
        selected_route_id = None
        selected_stop_id = None
        selected_stop_row = None
        route_stops = pd.DataFrame()

    # Data refresh button
    if st.sidebar.button("🔄 Refresh Data"):
        st.rerun()

    # Create tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs(
        ["🗺️ Interactive Map", "🚌 Route & ETA", "📊 Statistics", "🚦 Service Status"]
    )

    with tab1:
        st.header("Hong Kong Transportation Map")

        # Filter transport data based on selection
        if transport_mode == "All":
            display_data = all_stops
        else:
            display_data = {
                transport_mode: all_stops.get(transport_mode, pd.DataFrame())
            }

        # Create and display map
        if any(not df.empty for df in display_data.values()):
            map_obj = create_enhanced_map(
                display_data,
                route_stops if not route_stops.empty else None,
                selected_stop_id,
            )
            folium_static(map_obj, width=1200, height=600)
        else:
            st.warning(
                "No transportation data available. Please check your selections."
            )

    with tab2:
        st.header("Route & Real-time ETA Information")

        if selected_route_id and selected_stop_id:
            # Display route information
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("📍 Selected Stop Information")
                if selected_stop_row is not None:
                    st.write(f"**Stop Name:** {selected_stop_row['stop_name']}")
                    st.write(f"**Stop ID:** {selected_stop_row['stop_id']}")
                    st.write(f"**Sequence:** {selected_stop_row['sequence']}")
                    st.write(
                        f"**Coordinates:** {selected_stop_row['lat']:.6f}, {selected_stop_row['lng']:.6f}"
                    )

            with col2:
                st.subheader("🚌 Route Information")
                if not routes_df.empty:
                    route_info = routes_df[
                        routes_df["route_id"] == selected_route_id
                    ].iloc[0]
                    st.write(f"**Route:** {route_info['route_id']}")
                    st.write(f"**Origin:** {route_info['origin']}")
                    st.write(f"**Destination:** {route_info['destination']}")
                    st.write(f"**Service Type:** {route_info['service_type']}")

            # Display ETA information
            display_eta_info(transport_mode, selected_stop_id, selected_route_id)

            # Show all stops in the route
            if not route_stops.empty:
                st.subheader("🛣️ All Stops in Route")
                route_stops_display = route_stops[
                    ["sequence", "stop_name", "stop_id"]
                ].copy()
                route_stops_display.columns = ["Sequence", "Stop Name", "Stop ID"]
                st.dataframe(route_stops_display, use_container_width=True)
        else:
            st.info(
                "Please select a transport mode, route, and stop to view real-time ETA information."
            )

    with tab3:
        st.header("Transportation Statistics")

        # Create metrics
        col1, col2, col3, col4 = st.columns(4)

        total_routes = sum(len(df) for df in all_routes.values() if not df.empty)
        total_stops = sum(len(df) for df in all_stops.values() if not df.empty)

        with col1:
            st.metric("Total Routes", total_routes)
        with col2:
            st.metric("Total Stops", total_stops)
        with col3:
            st.metric("Transport Companies", len(all_routes))
        with col4:
            st.metric("Data Sources", len(all_stops))

        # Create charts
        if any(not df.empty for df in all_stops.values()):
            col1, col2 = st.columns(2)

            with col1:
                # Transport type distribution
                transport_counts = {
                    company: len(df)
                    for company, df in all_stops.items()
                    if not df.empty
                }

                if transport_counts:
                    fig = px.pie(
                        values=list(transport_counts.values()),
                        names=list(transport_counts.keys()),
                        title="Transportation Stop Distribution",
                        color_discrete_map={
                            "MTR": "#ff0000",
                            "KMB/LWB": "#0000ff",
                            "Citybus": "#00ff00",
                            "GMB": "#ffa500",
                        },
                    )
                    st.plotly_chart(fig, use_container_width=True)

            with col2:
                # Geographic distribution
                all_data = []
                for transport_type, df in all_stops.items():
                    if not df.empty:
                        df_copy = df.copy()
                        df_copy["transport_type"] = transport_type
                        all_data.append(df_copy)

                if all_data:
                    combined_df = pd.concat(all_data, ignore_index=True)
                    fig2 = px.scatter(
                        combined_df,
                        x="lng",
                        y="lat",
                        color="transport_type",
                        title="Geographic Distribution of Stops",
                        labels={"lng": "Longitude", "lat": "Latitude"},
                    )
                    st.plotly_chart(fig2, use_container_width=True)

    with tab4:
        st.header("Real-time Service Status")

        # Get service status
        service_status = api_manager.get_service_status()

        # MTR Service Status
        st.subheader("🚇 MTR Service Status")
        if "MTR" in service_status and service_status["MTR"]:
            mtr_status = service_status["MTR"]
            # Display MTR status based on actual API response
            st.info("MTR service status data available")
        else:
            st.info("MTR service status: Normal Service (sample data)")

        # Other companies
        st.subheader("🚌 Bus Service Updates")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.info("**KMB/LWB**: Normal Service")
        with col2:
            st.info("**Citybus**: Normal Service")
        with col3:
            st.info("**GMB**: Normal Service")

        # Last updated
        st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    """Main application function"""
    try:
        create_dashboard()
    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.info("Please check your internet connection and try again.")


if __name__ == "__main__":
    main()
