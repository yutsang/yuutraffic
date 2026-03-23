"""
Hong Kong KMB Bus Dashboard - Optimized Version
Single page layout with local caching and smart marker display
"""

import json
import os
from datetime import datetime

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from api_connectors import HKTransportAPIManager
from streamlit_folium import folium_static

# Page configuration
st.set_page_config(
    page_title="Hong Kong KMB Bus Dashboard",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Hong Kong coordinates
HK_CENTER = [22.3193, 114.1694]
HK_BOUNDARY = [[22.15, 113.8], [22.15, 114.5], [22.6, 114.5], [22.6, 113.8]]

# Local data cache file
CACHE_FILE = "kmb_data_cache.json"


def load_cached_data():
    """Load KMB data from local cache if available"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache_data = json.load(f)

            # Convert back to DataFrames
            data = {}
            for key, value in cache_data.items():
                if isinstance(value, dict):
                    if "data" in value:
                        # Direct DataFrame
                        data[key] = pd.DataFrame(value["data"])
                    else:
                        # Nested dictionary (routes/stops)
                        data[key] = {}
                        for sub_key, sub_value in value.items():
                            if isinstance(sub_value, dict) and "data" in sub_value:
                                data[key][sub_key] = pd.DataFrame(sub_value["data"])
                            else:
                                data[key][sub_key] = sub_value
                else:
                    data[key] = value
            return data
        except Exception as e:
            st.warning(f"Cache loading failed: {e}")
            # Remove corrupted cache file
            try:
                os.remove(CACHE_FILE)
            except:
                pass
    return None


def save_data_to_cache(data):
    """Save KMB data to local cache"""
    try:
        cache_data = {}
        for key, value in data.items():
            if isinstance(value, dict):
                # Handle nested dictionaries (like routes and stops)
                cache_data[key] = {}
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, pd.DataFrame):
                        cache_data[key][sub_key] = {
                            "data": sub_value.to_dict("records"),
                            "timestamp": datetime.now().isoformat(),
                        }
                    else:
                        cache_data[key][sub_key] = sub_value
            elif isinstance(value, pd.DataFrame):
                cache_data[key] = {
                    "data": value.to_dict("records"),
                    "timestamp": datetime.now().isoformat(),
                }
            else:
                cache_data[key] = value

        with open(CACHE_FILE, "w") as f:
            json.dump(cache_data, f)
    except Exception as e:
        st.warning(f"Cache saving failed: {e}")


@st.cache_resource
def get_api_manager():
    return HKTransportAPIManager()


@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_cached_routes():
    """Get cached KMB routes"""
    api_manager = get_api_manager()
    all_routes = api_manager.get_all_routes()
    # Only return KMB/LWB routes
    return {"KMB/LWB": all_routes.get("KMB/LWB", pd.DataFrame())}


@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_cached_stops():
    """Get cached KMB stops"""
    api_manager = get_api_manager()
    all_stops = api_manager.get_all_stops()
    # Only return KMB/LWB stops
    return {"KMB/LWB": all_stops.get("KMB/LWB", pd.DataFrame())}


@st.cache_data(ttl=300)
def get_cached_route_stops(route_id, direction=1, service_type=1):
    """Get cached stops for a specific KMB route, direction, and service type"""
    api_manager = get_api_manager()
    return api_manager.get_route_stops(route_id, direction, service_type)


@st.cache_data(ttl=60)  # Cache for 1 minute
def get_cached_eta(stop_id, route_id=None):
    """Get cached ETA for a specific KMB stop"""
    api_manager = get_api_manager()
    return api_manager.get_stop_eta(stop_id, route_id)


def create_optimized_map(selected_route_stops=None, selected_stop=None):
    """Create optimized map with KMB route stops and auto-recenter functionality"""
    # Calculate map center and bounds based on route stops
    if selected_route_stops is not None and not selected_route_stops.empty:
        # Get valid coordinates from route stops
        valid_coords = []
        for idx, row in selected_route_stops.iterrows():
            if pd.notna(row["lat"]) and pd.notna(row["lng"]):
                valid_coords.append([row["lat"], row["lng"]])

        if valid_coords:
            # Calculate center and bounds for the route
            lats = [coord[0] for coord in valid_coords]
            lngs = [coord[1] for coord in valid_coords]
            center_lat = sum(lats) / len(lats)
            center_lng = sum(lngs) / len(lngs)

            # Calculate bounds with some padding
            lat_padding = (max(lats) - min(lats)) * 0.1
            lng_padding = (max(lngs) - min(lngs)) * 0.1

            bounds = [
                [min(lats) - lat_padding, min(lngs) - lng_padding],
                [max(lats) + lat_padding, max(lngs) + lng_padding],
            ]

            # Create map centered on route
            m = folium.Map(
                location=[center_lat, center_lng],
                zoom_start=12,
                tiles="OpenStreetMap",
                zoom_control=True,
                scrollWheelZoom=True,
                dragging=True,
            )

            # Fit map to route bounds
            m.fit_bounds(bounds)
        else:
            # Fallback to Hong Kong center
            m = folium.Map(
                location=HK_CENTER,
                zoom_start=11,
                tiles="OpenStreetMap",
                zoom_control=True,
                scrollWheelZoom=True,
                dragging=True,
            )
    else:
        # Default Hong Kong view
        m = folium.Map(
            location=HK_CENTER,
            zoom_start=11,
            tiles="OpenStreetMap",
            zoom_control=True,
            scrollWheelZoom=True,
            dragging=True,
        )

    # Add Hong Kong boundary
    folium.Polygon(
        locations=HK_BOUNDARY,
        color="black",
        weight=2,
        fill=False,
        popup="Hong Kong SAR",
    ).add_to(m)

    # Only show route stops if a route is selected
    if selected_route_stops is not None and not selected_route_stops.empty:
        # Draw route path
        route_coords = []
        for idx, row in selected_route_stops.iterrows():
            if pd.notna(row["lat"]) and pd.notna(row["lng"]):
                route_coords.append([row["lat"], row["lng"]])

        if route_coords:
            # Add route line
            folium.PolyLine(
                locations=route_coords,
                color="purple",
                weight=3,
                opacity=0.8,
                popup=f"Route Path",
            ).add_to(m)

        # Add route stops to map
        for idx, row in selected_route_stops.iterrows():
            if pd.notna(row["lat"]) and pd.notna(row["lng"]):
                # Determine stop type for styling
                is_selected = selected_stop and row["stop_id"] == selected_stop
                is_depot = row["sequence"] in [1, len(selected_route_stops)]

                # Choose marker color and icon
                if is_selected:
                    color = "red"
                    icon = "star"
                elif is_depot:
                    color = "green"
                    icon = "home"
                else:
                    color = "blue"
                    icon = "bus"

                # Create popup content
                popup_content = f"""
                <b>KMB Stop: {row['stop_name']}</b><br>
                Stop ID: {row['stop_id']}<br>
                Sequence: {row['sequence']}<br>
                Type: {'🚌 Depot' if is_depot else '📍 Bus Stop'}<br>
                <a href="https://www.kmb.hk" target="_blank">More Info</a>
                """

                folium.Marker(
                    location=[row["lat"], row["lng"]],
                    popup=folium.Popup(popup_content, max_width=300),
                    icon=folium.Icon(color=color, icon=icon),
                    tooltip=f"KMB: {row['stop_name']} (Seq: {row['sequence']})",
                ).add_to(m)

    # Add legend
    legend_html = """
    <div style="position: fixed; 
                bottom: 50px; right: 50px; width: 220px; height: 120px; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:12px; padding: 10px">
    <p><b>KMB Bus Legend</b></p>
    <p><i class="fa fa-star" style="color:red"></i> Selected Stop</p>
    <p><i class="fa fa-home" style="color:green"></i> Depot/Terminal</p>
    <p><i class="fa fa-bus" style="color:blue"></i> Regular Stop</p>
    <p><i class="fa fa-route" style="color:purple"></i> Route Path</p>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m


def display_eta_info(stop_id, route_id=None):
    """Display ETA information for a KMB stop"""
    st.subheader("⏰ Real-time ETA")

    with st.spinner("Loading ETA..."):
        eta_data = get_cached_eta(stop_id, route_id)

    if eta_data.empty:
        st.warning("No ETA data available for this stop.")
        return

    # Display ETA information
    st.write("**Next Arrivals:**")

    for idx, row in eta_data.head(5).iterrows():  # Show next 5 arrivals
        route = row.get("route_id", "Unknown")
        destination = row.get("dest_en", "Unknown")
        eta = row.get("eta", "N/A")

        # Calculate time difference
        if eta != "N/A":
            try:
                eta_dt = datetime.fromisoformat(eta.replace("Z", "+00:00"))
                now = datetime.now(eta_dt.tzinfo)
                time_diff = eta_dt - now
                minutes_away = int(time_diff.total_seconds() / 60)

                if minutes_away < 0:
                    time_text = "🟢 Arrived"
                elif minutes_away < 3:
                    time_text = f"🟡 {minutes_away} min"
                else:
                    time_text = f"🔵 {minutes_away} min"
            except:
                time_text = eta
        else:
            time_text = "N/A"

        # Display in columns
        col1, col2, col3, col4 = st.columns([1, 2, 2, 1])

        with col1:
            st.markdown(f"**{route}**")
        with col2:
            st.markdown(f"**{destination}**")
        with col3:
            st.markdown(f"**{time_text}**")
        with col4:
            st.markdown("🚌")

        st.divider()


def create_dashboard():
    """Main dashboard function - single page layout"""
    st.markdown(
        '<h1 class="main-header">🚌 Hong Kong KMB Bus Dashboard</h1>',
        unsafe_allow_html=True,
    )

    # Check for cached data first
    cached_data = load_cached_data()

    if cached_data is None:
        # Load fresh data if no cache
        with st.spinner("Loading KMB data..."):
            all_routes = get_cached_routes()
            all_stops = get_cached_stops()
            # Save to cache
            save_data_to_cache({"routes": all_routes, "stops": all_stops})
    else:
        all_routes = cached_data.get("routes", {})
        all_stops = cached_data.get("stops", {})
        st.success("✅ Using cached KMB data for faster loading")

    # Sidebar controls
    st.sidebar.header("🚌 KMB Bus Controls")

    # Route selection
    selected_route_id = None
    selected_stop_id = None
    selected_stop_row = None
    route_stops = pd.DataFrame()

    # Only work with KMB/LWB data
    if "KMB/LWB" in all_routes:
        routes_df = all_routes["KMB/LWB"]
        if not routes_df.empty:
            # Create unique route options by combining route_id with origin and destination
            unique_routes = []
            seen_routes = set()

            for idx, row in routes_df.iterrows():
                route_key = f"{row['route_id']}_{row['origin']}_{row['destination']}"
                if route_key not in seen_routes:
                    seen_routes.add(route_key)
                    route_display = (
                        f"{row['route_id']} - {row['origin']} → {row['destination']}"
                    )
                    unique_routes.append(
                        {
                            "display": route_display,
                            "route_id": row["route_id"],
                            "origin": row["origin"],
                            "destination": row["destination"],
                            "service_type": row.get("service_type", "1"),
                            "bound": row.get("bound", "O"),
                        }
                    )

            route_options = [route["display"] for route in unique_routes]
            selected_route_display = st.sidebar.selectbox(
                "Select KMB Route", ["None"] + route_options
            )

            if selected_route_display != "None":
                # Find the selected route details
                selected_route = None
                for route in unique_routes:
                    if route["display"] == selected_route_display:
                        selected_route = route
                        break

                if selected_route:
                    selected_route_id = selected_route["route_id"]

                    # Get direction and service_type options
                    direction = 1
                    service_type = 1

                    # Find all variants of this route
                    route_variants = routes_df[
                        (routes_df["route_id"] == selected_route_id)
                        & (routes_df["origin"] == selected_route["origin"])
                        & (routes_df["destination"] == selected_route["destination"])
                    ]

                    if len(route_variants) > 1:
                        # Show direction selection if multiple variants exist
                        direction_options = []
                        for _, variant in route_variants.iterrows():
                            bound_text = (
                                "Outbound" if variant.get("bound") == "O" else "Inbound"
                            )
                            direction_options.append(
                                f"{bound_text} (Service {variant.get('service_type', '1')})"
                            )

                        selected_direction_display = st.sidebar.selectbox(
                            "Direction & Service Type", direction_options, index=0
                        )

                        # Extract direction and service type from selection
                        selected_variant_idx = direction_options.index(
                            selected_direction_display
                        )
                        selected_variant = route_variants.iloc[selected_variant_idx]
                        direction = 1 if selected_variant.get("bound") == "O" else 2
                        service_type = int(selected_variant.get("service_type", 1))
                    else:
                        # Single variant, use default values
                        direction = 1 if selected_route["bound"] == "O" else 2
                        service_type = int(selected_route["service_type"])

        # Get route stops if a route is selected
        if selected_route_id:
            with st.spinner("Loading route stops..."):
                route_stops = get_cached_route_stops(
                    selected_route_id, direction, service_type
                )
                if not route_stops.empty:
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

    # Data refresh button
    if st.sidebar.button("🔄 Refresh Data"):
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        st.rerun()

    # Main content area
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("🗺️ Interactive KMB Route Map")

        # Create and display map
        map_obj = create_optimized_map(
            route_stops if not route_stops.empty else None, selected_stop_id
        )
        folium_static(map_obj, width=800, height=500)

    with col2:
        st.subheader("📊 KMB Statistics")

        # Calculate statistics
        total_routes = len(all_routes.get("KMB/LWB", pd.DataFrame()))
        total_stops = len(all_stops.get("KMB/LWB", pd.DataFrame()))

        st.metric("Total KMB Routes", total_routes)
        st.metric("Total KMB Stops", total_stops)

        if selected_route_id:
            st.metric("Route Stops", len(route_stops))

        # KMB service info
        st.subheader("KMB Service Info")
        st.info("**Service Area**: Kowloon & New Territories")
        st.info("**Daily Passengers**: ~2.8M")
        st.info("**Fleet Size**: ~4,000 buses")

        # Route distribution chart
        if not all_routes.get("KMB/LWB", pd.DataFrame()).empty:
            routes_df = all_routes["KMB/LWB"]
            service_counts = (
                routes_df.groupby("service_type").size().reset_index(name="count")
            )
            fig = px.bar(
                service_counts,
                x="service_type",
                y="count",
                title="Routes by Service Type",
                color="count",
                color_continuous_scale="Blues",
            )
            st.plotly_chart(fig, use_container_width=True)

    # Route and ETA information
    if selected_route_id and selected_stop_id:
        st.subheader("🚌 Route & ETA Information")

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
            if "KMB/LWB" in all_routes:
                routes_df = all_routes["KMB/LWB"]
                if not routes_df.empty:
                    route_info = routes_df[
                        routes_df["route_id"] == selected_route_id
                    ].iloc[0]
                    st.write(f"**Route:** {route_info['route_id']}")
                    st.write(f"**Origin:** {route_info['origin']}")
                    st.write(f"**Destination:** {route_info['destination']}")
                    st.write(f"**Service Type:** {route_info['service_type']}")

        # Display ETA information
        display_eta_info(selected_stop_id, selected_route_id)

        # Show all stops in the route with ETA
        if not route_stops.empty:
            st.subheader("🛣️ All Stops in Route with ETA")

            # Create enhanced route display with ETA
            route_display_data = []
            for idx, stop_row in route_stops.iterrows():
                # Get ETA for this stop
                stop_eta = get_cached_eta(stop_row["stop_id"], selected_route_id)

                # Calculate next arrival time
                next_arrival = "N/A"
                if not stop_eta.empty:
                    eta_time = stop_eta.iloc[0].get("eta", "N/A")
                    if eta_time != "N/A":
                        try:
                            eta_dt = datetime.fromisoformat(
                                eta_time.replace("Z", "+00:00")
                            )
                            now = datetime.now(eta_dt.tzinfo)
                            time_diff = eta_dt - now
                            minutes_away = int(time_diff.total_seconds() / 60)

                            if minutes_away < 0:
                                next_arrival = "🟢 Arrived"
                            elif minutes_away < 5:
                                next_arrival = f"🟡 {minutes_away} min"
                            else:
                                next_arrival = f"🔵 {minutes_away} min"
                        except:
                            next_arrival = eta_time

                route_display_data.append(
                    {
                        "Sequence": stop_row["sequence"],
                        "Stop Name": stop_row["stop_name"],
                        "Stop ID": stop_row["stop_id"],
                        "Next Arrival": next_arrival,
                        "Type": "🚌 Depot"
                        if "Depot" in stop_row["stop_name"]
                        or stop_row["sequence"] in [1, len(route_stops)]
                        else "📍 Stop",
                    }
                )

            # Display as dataframe with styling
            route_df = pd.DataFrame(route_display_data)
            st.dataframe(route_df, use_container_width=True)

            # Show depot information
            if len(route_stops) >= 2:
                first_stop = route_stops.iloc[0]
                last_stop = route_stops.iloc[-1]

                st.subheader("🏢 Depot Information")
                col1, col2 = st.columns(2)

                with col1:
                    st.info(f"**Starting Point:** {first_stop['stop_name']}")
                    st.write(
                        f"Location: {first_stop['lat']:.6f}, {first_stop['lng']:.6f}"
                    )

                with col2:
                    st.info(f"**Ending Point:** {last_stop['stop_name']}")
                    st.write(
                        f"Location: {last_stop['lat']:.6f}, {last_stop['lng']:.6f}"
                    )

    elif selected_route_id:
        st.subheader("🚌 Route Information")
        if "KMB/LWB" in all_routes:
            routes_df = all_routes["KMB/LWB"]
            if not routes_df.empty:
                route_info = routes_df[routes_df["route_id"] == selected_route_id].iloc[
                    0
                ]
                st.write(f"**Route:** {route_info['route_id']}")
                st.write(f"**Origin:** {route_info['origin']}")
                st.write(f"**Destination:** {route_info['destination']}")
                st.write(f"**Service Type:** {route_info['service_type']}")

        if not route_stops.empty:
            st.subheader("🛣️ Route Stops")

            # Show route overview
            col1, col2 = st.columns(2)

            with col1:
                st.metric("Total Stops", len(route_stops))
                st.metric("Route Length", f"{len(route_stops)} stops")

            with col2:
                first_stop = route_stops.iloc[0]
                last_stop = route_stops.iloc[-1]
                st.write(f"**From:** {first_stop['stop_name']}")
                st.write(f"**To:** {last_stop['stop_name']}")

            # Display stops with depot highlighting
            route_stops_display = route_stops[
                ["sequence", "stop_name", "stop_id"]
            ].copy()
            route_stops_display.columns = ["Sequence", "Stop Name", "Stop ID"]

            # Add depot indicator
            route_stops_display["Type"] = route_stops_display["Sequence"].apply(
                lambda x: "🚌 Depot" if x in [1, len(route_stops)] else "📍 Stop"
            )

            st.dataframe(route_stops_display, use_container_width=True)

    else:
        st.info(
            "💡 **Tip**: Select a KMB route to view detailed information and see stops on the map."
        )

    # KMB service status at the bottom
    st.subheader("🚦 KMB Service Status")

    # Get service status
    api_manager = get_api_manager()
    service_status = api_manager.get_service_status()

    if "KMB/LWB" in service_status:
        status = service_status["KMB/LWB"].get("status", "Normal Service")
        if status == "Normal Service":
            st.success("🟢 **KMB/LWB**: Normal Service")
        else:
            st.warning(f"🟡 **KMB/LWB**: {status}")
    else:
        st.success("🟢 **KMB/LWB**: Normal Service")

    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    """Main function"""
    # Custom CSS for better styling
    st.markdown(
        """
    <style>
    .main-header {
        background: linear-gradient(90deg, #0066cc 0%, #3399ff 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    create_dashboard()


if __name__ == "__main__":
    main()
