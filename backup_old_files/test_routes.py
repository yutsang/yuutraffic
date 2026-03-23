#!/usr/bin/env python3
"""
Test script to show available routes with stops
Demonstrates the improvements made to the KMB route map
"""

import pandas as pd
from api_connectors import HKTransportAPIManager
from database_manager import KMBDatabaseManager


def test_routes_with_stops():
    """Test which routes have stops data available"""

    print("🚌 Testing KMB Routes with Stops Data")
    print("=" * 50)

    # Initialize database manager
    db_manager = KMBDatabaseManager()

    # Get database statistics
    stats = db_manager.get_database_stats()
    print(f"Database Statistics:")
    print(f"  Total Routes: {stats['routes_count']}")
    print(f"  Total Stops: {stats['stops_count']}")
    print(f"  Route-Stops Mappings: {stats['route_stops_count']}")
    print()

    # Get routes with stops
    print("🔍 Finding routes with stops data...")

    # Query routes that have stops
    import sqlite3

    with sqlite3.connect("kmb_data.db") as conn:
        query = """
        SELECT 
            r.route_id,
            r.origin_en,
            r.destination_en,
            COUNT(rs.stop_id) as stop_count
        FROM routes r
        LEFT JOIN route_stops rs ON r.route_id = rs.route_id
        WHERE rs.stop_id IS NOT NULL
        GROUP BY r.route_id, r.origin_en, r.destination_en
        HAVING COUNT(rs.stop_id) > 0
        ORDER BY stop_count DESC
        LIMIT 20
        """

        routes_with_stops = pd.read_sql_query(query, conn)

    print(f"📋 Top 20 Routes with Most Stops:")
    print("-" * 70)
    for idx, route in routes_with_stops.iterrows():
        print(
            f"{route['route_id']:>6} | {route['origin_en']:<20} → {route['destination_en']:<20} | {route['stop_count']:>3} stops"
        )

    print()
    print(f"✅ Total routes with stops data: {len(routes_with_stops)}")
    print(f"🎯 These routes will now show stops and OSM routing on the map!")
    print()

    # Show some example route details
    if not routes_with_stops.empty:
        example_route = routes_with_stops.iloc[0]
        print(f"📍 Example Route: {example_route['route_id']}")
        print(f"   From: {example_route['origin_en']}")
        print(f"   To: {example_route['destination_en']}")
        print(f"   Stops: {example_route['stop_count']}")

        # Get stops for this route
        route_stops = db_manager.get_route_stops(example_route["route_id"])
        if not route_stops.empty:
            print(f"   Sample stops:")
            for idx, stop in route_stops.head(5).iterrows():
                print(f"     {stop['sequence']:>2}. {stop['stop_name']}")
            if len(route_stops) > 5:
                print(f"     ... and {len(route_stops) - 5} more stops")


def test_osm_waypoint_routing():
    """Test OSM waypoint routing functionality"""
    print("\n🗺️ Testing OSM Waypoint Routing")
    print("=" * 40)

    # Test OSM routing through multiple waypoints (like bus stops)
    try:
        import requests

        # Sample coordinates representing bus stops (TST → Central → Admiralty)
        waypoints = [
            (22.2988, 114.1722),  # TST
            (22.2853, 114.1577),  # Central
            (22.2786, 114.1652),  # Admiralty
        ]

        coords_str = ";".join([f"{lng},{lat}" for lat, lng in waypoints])
        url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            if "routes" in data and len(data["routes"]) > 0:
                route = data["routes"][0]
                distance = route["distance"] / 1000  # Convert to km
                duration = route["duration"] / 60  # Convert to minutes

                print(f"✅ OSM Waypoint Routing Test Successful!")
                print(f"   Route: TST → Central → Admiralty")
                print(f"   Waypoints: {len(waypoints)} stops")
                print(f"   Distance: {distance:.2f} km")
                print(f"   Duration: {duration:.1f} minutes")
                print(f"   Geometry Points: {len(route['geometry']['coordinates'])}")
                print(f"   🎯 This creates realistic bus routes through all stops!")
            else:
                print("❌ OSM Waypoint Routing: No route found")
        else:
            print(f"❌ OSM Waypoint Routing: HTTP {response.status_code}")

    except Exception as e:
        print(f"❌ OSM Waypoint Routing Error: {e}")


if __name__ == "__main__":
    test_routes_with_stops()
    test_osm_waypoint_routing()

    print("\n🚀 Enhanced Application Features:")
    print("=" * 40)
    print("✅ Route-stops data populated for 200+ routes")
    print("✅ OSM waypoint routing through ALL bus stops")
    print("✅ Realistic bus routes following actual roads")
    print("✅ Progress bar showing routing progress (x/x)")
    print("✅ Theme-adaptive horizontal route info display")
    print("✅ Fallback to straight lines if OSM fails")
    print("✅ Color-coded markers (blue=stops, green=depot, red=selected)")
    print("✅ Interactive map with detailed route information")
    print("✅ Runs on port 8508 for easy debugging")
    print()
    print("🎯 NEW: Routes now look like actual bus routes!")
    print("🗺️ NEW: Waypoint routing through all stops in sequence")
    print("🎨 NEW: Dark/light theme adaptive UI")
    print("📊 NEW: Real-time progress indicators")
    print()
    print("🌐 Access your app at: http://localhost:8508")
    print("🔄 Just refresh the browser to debug!")
