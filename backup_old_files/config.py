"""
Configuration file for Hong Kong KMB Bus Dashboard
"""

# Hong Kong Geographic Settings
HK_CENTER = [22.3193, 114.1694]  # Central Hong Kong coordinates
HK_BOUNDARY = [[22.15, 113.8], [22.15, 114.5], [22.6, 114.5], [22.6, 113.8]]

# KMB API Endpoints
API_ENDPOINTS = {
    "kmb_lwb": {
        "base_url": "https://data.etabus.gov.hk/v1/transport/kmb",
        "routes": "https://data.etabus.gov.hk/v1/transport/kmb/route",
        "stops": "https://data.etabus.gov.hk/v1/transport/kmb/stop",
        "eta": "https://data.etabus.gov.hk/v1/transport/kmb/eta",
        "route_stop": "https://data.etabus.gov.hk/v1/transport/kmb/route-stop",
        "stop_eta": "https://data.etabus.gov.hk/v1/transport/kmb/stop-eta",
    }
}

# Map Configuration
MAP_CONFIG = {
    "default_zoom": 11,
    "tile_layers": {
        "OpenStreetMap": "OpenStreetMap",
        "CartoDB positron": "CartoDB positron",
        "CartoDB dark_matter": "CartoDB dark_matter",
        "Stamen Terrain": "Stamen Terrain",
    },
    "marker_colors": {"KMB": "blue", "Selected": "red", "Depot": "green"},
    "marker_icons": {"KMB": "bus", "Selected": "star", "Depot": "home"},
}

# UI Configuration
UI_CONFIG = {
    "page_title": "Hong Kong KMB Bus Dashboard",
    "page_icon": "🚌",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
    "refresh_interval": 300,  # seconds
    "max_markers": 1000,  # maximum markers to display for performance
}

# Data Configuration
DATA_CONFIG = {
    "cache_timeout": 300,  # seconds
    "max_retries": 3,
    "timeout": 10,
    "use_local_database": True,  # Use local SQLite database for routes and stops
    "database_path": "kmb_data.db",  # Path to SQLite database
}

# KMB Service Status Configuration
SERVICE_STATUS = {
    "kmb_lwb": {
        "status": "Normal Service",
        "coverage": "Kowloon & New Territories",
        "fleet_size": "4000+ buses",
        "daily_passengers": "2.8M+",
        "routes": "400+ routes",
    }
}

# KMB Analytics Configuration
ANALYTICS_CONFIG = {
    "peak_hours": {"morning": [7, 8, 9], "evening": [17, 18, 19]},
    "service_types": ["Regular", "Express", "Special"],
    "popular_routes": ["1A", "2", "3C", "6", "7", "8", "9"],
    "coverage_areas": ["Kowloon", "New Territories"],
    "performance_metrics": {
        "on_time_percentage": 94.2,
        "average_journey_time": 28,
        "customer_satisfaction": 4.1,
    },
}

# KMB Route Categories
ROUTE_CATEGORIES = {
    "regular": {"color": "#0066cc", "description": "Regular scheduled services"},
    "express": {
        "color": "#ff6600",
        "description": "Express services with limited stops",
    },
    "special": {
        "color": "#009900",
        "description": "Special event or peak-hour services",
    },
}
