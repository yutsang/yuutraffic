#!/usr/bin/env python3
"""
Example usage of the new KMB database-based system

This script demonstrates how to:
1. Check database status
2. Update database with latest data
3. Query routes and stops from the database
4. Only fetch ETA data from the API in real-time
"""

import os
import sys
from datetime import datetime

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from api_connectors import KMBLWBConnector
from data_updater import KMBDataUpdater
from database_manager import KMBDatabaseManager


def demonstrate_system():
    """Demonstrate the new database-based system"""
    print("🚌 KMB Database-based System Demo")
    print("=" * 50)

    # Initialize components
    db_manager = KMBDatabaseManager()
    data_updater = KMBDataUpdater()
    api_connector = KMBLWBConnector()

    print("\n1. 📊 Database Status")
    print("-" * 20)

    # Check database status
    stats = db_manager.get_database_stats()
    print(f"Routes in database: {stats['routes_count']}")
    print(f"Stops in database: {stats['stops_count']}")
    print(f"Route-stops in database: {stats['route_stops_count']}")

    if stats["last_routes_update"]:
        print(f"Last routes update: {stats['last_routes_update']}")

    is_stale = db_manager.is_data_stale()
    print(f"Data is stale: {is_stale}")

    # If database is empty or stale, offer to update
    if stats["routes_count"] == 0 or stats["stops_count"] == 0:
        print("\n⚠️  Database is empty!")
        print("Run this script with --update flag to populate the database.")
        print("Example: python example_usage.py --update")
        return
    elif is_stale:
        print("\n⚠️  Database data is stale (>24 hours old)")
        print("Consider running: python data_updater.py --all")

    print("\n2. 🗺️ Querying Routes from Database")
    print("-" * 30)

    # Get routes from database (not API)
    routes = api_connector.get_routes()
    print(f"Total routes available: {len(routes)}")

    if not routes.empty:
        print("\nSample routes:")
        for i, route in routes.head(5).iterrows():
            print(f"  {route['route_id']}: {route['origin']} → {route['destination']}")

    print("\n3. 📍 Querying Stops from Database")
    print("-" * 30)

    # Get stops from database (not API)
    stops = api_connector.get_stops()
    print(f"Total stops available: {len(stops)}")

    if not stops.empty:
        print("\nSample stops:")
        for i, stop in stops.head(5).iterrows():
            print(f"  {stop['stop_id']}: {stop['stop_name']}")

    print("\n4. 🚌 Route Stops from Database")
    print("-" * 30)

    # Get route stops for a specific route
    if not routes.empty:
        sample_route = routes.iloc[0]["route_id"]
        print(f"Getting stops for route {sample_route}:")

        route_stops = api_connector.get_route_stops(sample_route)
        print(f"Stops for route {sample_route}: {len(route_stops)}")

        if not route_stops.empty:
            print("\nRoute stops:")
            for i, stop in route_stops.head(3).iterrows():
                print(f"  {stop['sequence']}: {stop['stop_name']} ({stop['stop_id']})")

    print("\n5. ⏰ Real-time ETA (from API)")
    print("-" * 30)

    # Only ETA data comes from API
    if not stops.empty:
        sample_stop = stops.iloc[0]["stop_id"]
        print(f"Getting ETA for stop {sample_stop}:")

        eta_data = api_connector.get_stop_eta(sample_stop)
        if not eta_data.empty:
            print(f"ETA data available: {len(eta_data)} entries")
            print("✅ ETA data successfully fetched from API")
        else:
            print("⚠️ No ETA data available (API might be unavailable)")

    print("\n6. 📈 Update History")
    print("-" * 15)

    # Show recent updates
    update_history = db_manager.get_update_history(5)
    if not update_history.empty:
        print("Recent updates:")
        for i, update in update_history.iterrows():
            print(
                f"  {update['updated_at']}: {update['update_type']} - {update['status']} ({update['records_updated']} records)"
            )
    else:
        print("No update history available")

    print("\n✅ Demo completed!")
    print("\nKey benefits:")
    print("- Routes and stops are stored locally (fast access)")
    print("- No API calls needed for basic route/stop information")
    print("- Only ETA data is fetched from API in real-time")
    print("- Database can be updated daily or on-demand")
    print("- Reduced API load and improved performance")


def update_database_demo():
    """Demonstrate database update process"""
    print("🔄 Database Update Demo")
    print("=" * 30)

    print("This will fetch data from KMB API and update the local database.")
    print("This may take a few minutes...")

    # Ask for confirmation
    confirm = input("\nProceed with update? (y/N): ")
    if confirm.lower() != "y":
        print("Update cancelled.")
        return

    # Update database
    data_updater = KMBDataUpdater()

    print("\n1. Updating routes...")
    routes_success = data_updater.update_routes()

    print("\n2. Updating stops...")
    stops_success = data_updater.update_stops()

    print("\n3. Updating route-stops (this may take a while)...")
    # Limit to first 10 routes for demo
    route_stops_success = data_updater.update_route_stops(max_routes=10)

    if routes_success and stops_success and route_stops_success:
        print("\n✅ Database update completed successfully!")

        # Show updated stats
        db_manager = KMBDatabaseManager()
        stats = db_manager.get_database_stats()
        print(f"Routes: {stats['routes_count']}")
        print(f"Stops: {stats['stops_count']}")
        print(f"Route-stops: {stats['route_stops_count']}")
    else:
        print("\n❌ Database update completed with errors. Check the logs for details.")


def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description="Demo the KMB database-based system")
    parser.add_argument(
        "--update", action="store_true", help="Update database before demo"
    )

    args = parser.parse_args()

    if args.update:
        update_database_demo()
        print("\n" + "=" * 50)

    demonstrate_system()


if __name__ == "__main__":
    main()
