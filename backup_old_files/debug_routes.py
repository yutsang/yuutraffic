#!/usr/bin/env python3
"""
Debug script to investigate missing routes
"""
import os
import sqlite3
import sys

import pandas as pd

# Add the pipelines to the path
sys.path.append(
    os.path.join(
        os.path.dirname(__file__), "src", "hk_kmb_transport", "pipelines", "web_app"
    )
)

from src.hk_kmb_transport.pipelines.web_app.nodes import (
    get_route_stops_with_directions,
    get_sorted_routes,
    load_kmb_data,
    natural_sort_key,
)


def debug_missing_routes():
    """Debug the missing routes issue"""
    print("🔍 Debugging missing routes issue...")
    print("=" * 50)

    # Load data using the production function
    print("Loading data...")
    routes_df, stops_df = load_kmb_data()
    print(f"Loaded {len(routes_df)} routes and {len(stops_df)} stops")

    # Check specific routes in the dataframe
    missing_routes = ["24", "213X", "219X"]

    print("\n1. Checking if routes exist in routes_df:")
    for route in missing_routes:
        route_data = routes_df[routes_df["route_id"] == route]
        if not route_data.empty:
            print(
                f"✅ Route {route} found: {route_data.iloc[0]['origin']} → {route_data.iloc[0]['destination']}"
            )
        else:
            print(f"❌ Route {route} NOT found in routes_df")

    # Check if they appear in sorted routes
    print("\n2. Checking if routes appear in sorted routes:")
    sorted_routes = get_sorted_routes(routes_df)
    for route in missing_routes:
        route_data = sorted_routes[sorted_routes["route_id"] == route]
        if not route_data.empty:
            print(f"✅ Route {route} found in sorted routes")
        else:
            print(f"❌ Route {route} NOT found in sorted routes")

    # Check if they have route stops
    print("\n3. Checking if routes have stops:")
    for route in missing_routes:
        route_stops = get_route_stops_with_directions(route)
        if not route_stops.empty:
            print(f"✅ Route {route} has {len(route_stops)} stops")
            directions = route_stops["direction"].unique()
            print(f"   Directions: {directions}")
        else:
            print(f"❌ Route {route} has NO stops")

    # Test natural sorting
    print("\n4. Testing natural sorting:")
    test_routes = ["1", "2", "3", "10", "11", "24", "101", "213X", "219X"]
    for route in test_routes:
        key = natural_sort_key(route)
        print(f"Route {route}: sort key = {key}")

    # Check if routes are in the first 50 sorted routes
    print("\n5. Checking first 50 sorted routes:")
    first_50 = sorted_routes.head(50)["route_id"].tolist()
    for route in missing_routes:
        if route in first_50:
            print(f"✅ Route {route} is in first 50 sorted routes")
        else:
            print(f"❌ Route {route} is NOT in first 50 sorted routes")

    # Find where these routes appear in the sorted list
    print("\n6. Finding position of routes in sorted list:")
    for route in missing_routes:
        route_data = sorted_routes[sorted_routes["route_id"] == route]
        if not route_data.empty:
            position = sorted_routes[sorted_routes["route_id"] == route].index[0]
            print(f"Route {route} is at position {position} in sorted list")
        else:
            print(f"Route {route} not found in sorted list")

    # Print some surrounding routes
    print("\n7. Routes around position 20-30:")
    sample_routes = sorted_routes.iloc[20:30]
    for idx, row in sample_routes.iterrows():
        print(f"  {row['route_id']} - {row['origin']} → {row['destination']}")

    print("\n8. Sample search test:")
    # Test search functionality
    search_terms = ["24", "213", "219"]
    for term in search_terms:
        mask = (
            sorted_routes["route_id"].str.contains(term, case=False, na=False)
            | sorted_routes["origin"].str.contains(term, case=False, na=False)
            | sorted_routes["destination"].str.contains(term, case=False, na=False)
        )
        filtered = sorted_routes[mask]
        print(f"Search '{term}' found {len(filtered)} routes:")
        for idx, row in filtered.head(5).iterrows():
            print(f"  {row['route_id']} - {row['origin']} → {row['destination']}")


if __name__ == "__main__":
    debug_missing_routes()
