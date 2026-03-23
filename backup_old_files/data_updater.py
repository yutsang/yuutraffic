"""
Data Updater for KMB Transportation Data

This script fetches KMB routes and stops data from the official API
and stores it in the local database for offline use.
"""

import logging
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests
from database_manager import KMBDatabaseManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("data_updater.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class KMBDataUpdater:
    """Fetches and updates KMB data from the official API"""

    def __init__(self, db_path: str = "kmb_data.db"):
        """
        Initialize the data updater

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_manager = KMBDatabaseManager(db_path)
        self.base_url = "https://data.etabus.gov.hk/v1/transport/kmb"
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "KMB-Dashboard/1.0", "Accept": "application/json"}
        )

    def fetch_routes(self) -> List[Dict]:
        """
        Fetch all KMB routes from the API

        Returns:
            List of route dictionaries
        """
        try:
            logger.info("Fetching KMB routes from API...")
            url = f"{self.base_url}/route"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            data = response.json()
            if "data" in data:
                logger.info(f"Fetched {len(data['data'])} routes")
                return data["data"]
            else:
                logger.error("No 'data' field in API response")
                return []

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching routes: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching routes: {e}")
            return []

    def fetch_stops(self) -> List[Dict]:
        """
        Fetch all KMB stops from the API

        Returns:
            List of stop dictionaries
        """
        try:
            logger.info("Fetching KMB stops from API...")
            url = f"{self.base_url}/stop"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            data = response.json()
            if "data" in data:
                logger.info(f"Fetched {len(data['data'])} stops")
                return data["data"]
            else:
                logger.error("No 'data' field in API response")
                return []

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching stops: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching stops: {e}")
            return []

    def fetch_route_stops(
        self, route_id: str, direction: str = "outbound", service_type: int = 1
    ) -> List[Dict]:
        """
        Fetch stops for a specific route from the API

        Args:
            route_id: Route identifier
            direction: Direction ("outbound" or "inbound")
            service_type: Service type (usually 1)

        Returns:
            List of route-stop dictionaries
        """
        try:
            url = f"{self.base_url}/route-stop/{route_id}/{direction}/{service_type}"
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            data = response.json()
            if "data" in data:
                return data["data"]
            else:
                return []

        except requests.exceptions.RequestException as e:
            logger.warning(f"Error fetching route stops for {route_id}: {e}")
            return []
        except Exception as e:
            logger.warning(f"Unexpected error fetching route stops for {route_id}: {e}")
            return []

    def fetch_all_route_stops(self, routes: List[Dict]) -> List[Dict]:
        """
        Fetch stops for all routes (with rate limiting)

        Args:
            routes: List of route dictionaries

        Returns:
            List of all route-stop dictionaries
        """
        all_route_stops = []
        total_routes = len(routes)

        logger.info(f"Fetching route stops for {total_routes} routes...")

        for i, route in enumerate(routes):
            route_id = route.get(
                "route_id"
            )  # Database field is 'route_id', not 'route'
            if not route_id:
                continue

            # Fetch for both directions
            for direction_name, direction_bound in [
                ("outbound", "O"),
                ("inbound", "I"),
            ]:
                route_stops = self.fetch_route_stops(route_id, direction_name)
                for route_stop in route_stops:
                    route_stop["route"] = route_id
                    route_stop["bound"] = direction_bound
                    all_route_stops.append(route_stop)

                # Rate limiting - small delay between requests
                time.sleep(0.1)

            # Log progress
            if (i + 1) % 50 == 0:
                logger.info(f"Processed {i + 1}/{total_routes} routes")

        logger.info(f"Fetched {len(all_route_stops)} route-stop mappings")
        return all_route_stops

    def update_routes(self) -> bool:
        """
        Update routes data in the database

        Returns:
            True if successful, False otherwise
        """
        try:
            routes = self.fetch_routes()
            if not routes:
                self.db_manager.log_update(
                    "routes", 0, "error", "No routes data fetched"
                )
                return False

            updated_count = self.db_manager.insert_routes(routes)
            self.db_manager.log_update("routes", updated_count, "success")
            logger.info(f"Successfully updated {updated_count} routes")
            return True

        except Exception as e:
            error_msg = f"Error updating routes: {e}"
            logger.error(error_msg)
            self.db_manager.log_update("routes", 0, "error", error_msg)
            return False

    def update_stops(self) -> bool:
        """
        Update stops data in the database

        Returns:
            True if successful, False otherwise
        """
        try:
            stops = self.fetch_stops()
            if not stops:
                self.db_manager.log_update("stops", 0, "error", "No stops data fetched")
                return False

            updated_count = self.db_manager.insert_stops(stops)
            self.db_manager.log_update("stops", updated_count, "success")
            logger.info(f"Successfully updated {updated_count} stops")
            return True

        except Exception as e:
            error_msg = f"Error updating stops: {e}"
            logger.error(error_msg)
            self.db_manager.log_update("stops", 0, "error", error_msg)
            return False

    def update_route_stops(self, max_routes: Optional[int] = None) -> bool:
        """
        Update route-stops data in the database

        Args:
            max_routes: Maximum number of routes to process (for testing)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get routes from database (should be updated first)
            routes_df = self.db_manager.get_routes()
            if routes_df.empty:
                error_msg = "No routes in database. Update routes first."
                logger.error(error_msg)
                self.db_manager.log_update("route_stops", 0, "error", error_msg)
                return False

            # Convert to list format
            routes = routes_df.to_dict("records")

            # Limit routes for testing if specified
            if max_routes:
                routes = routes[:max_routes]
                logger.info(f"Limiting to {max_routes} routes for testing")

            route_stops = self.fetch_all_route_stops(routes)
            if not route_stops:
                self.db_manager.log_update(
                    "route_stops", 0, "error", "No route-stops data fetched"
                )
                return False

            updated_count = self.db_manager.insert_route_stops(route_stops)
            self.db_manager.log_update("route_stops", updated_count, "success")
            logger.info(f"Successfully updated {updated_count} route-stop mappings")
            return True

        except Exception as e:
            error_msg = f"Error updating route-stops: {e}"
            logger.error(error_msg)
            self.db_manager.log_update("route_stops", 0, "error", error_msg)
            return False

    def update_all_data(self, max_routes: Optional[int] = None) -> bool:
        """
        Update all data (routes, stops, route-stops)

        Args:
            max_routes: Maximum number of routes to process (for testing)

        Returns:
            True if all updates successful, False otherwise
        """
        logger.info("Starting full data update...")

        success = True

        # Update routes
        if not self.update_routes():
            success = False

        # Update stops
        if not self.update_stops():
            success = False

        # Update route-stops (this takes a while)
        if not self.update_route_stops(max_routes):
            success = False

        if success:
            logger.info("Full data update completed successfully")
        else:
            logger.error("Full data update completed with errors")

        return success

    def get_update_status(self) -> Dict:
        """
        Get database update status

        Returns:
            Dictionary with update status information
        """
        stats = self.db_manager.get_database_stats()
        is_stale = self.db_manager.is_data_stale()

        return {
            "routes_count": stats["routes_count"],
            "stops_count": stats["stops_count"],
            "route_stops_count": stats["route_stops_count"],
            "last_routes_update": stats["last_routes_update"],
            "last_stops_update": stats["last_stops_update"],
            "is_stale": is_stale,
        }


def main():
    """Main function for command-line usage"""
    import argparse

    parser = argparse.ArgumentParser(description="Update KMB transportation data")
    parser.add_argument("--routes", action="store_true", help="Update routes only")
    parser.add_argument("--stops", action="store_true", help="Update stops only")
    parser.add_argument(
        "--route-stops", action="store_true", help="Update route-stops only"
    )
    parser.add_argument("--all", action="store_true", help="Update all data")
    parser.add_argument(
        "--max-routes", type=int, help="Maximum number of routes to process"
    )
    parser.add_argument("--status", action="store_true", help="Show update status")
    parser.add_argument("--db-path", default="kmb_data.db", help="Database file path")

    args = parser.parse_args()

    updater = KMBDataUpdater(args.db_path)

    if args.status:
        status = updater.get_update_status()
        print(f"Database Status:")
        print(f"  Routes: {status['routes_count']}")
        print(f"  Stops: {status['stops_count']}")
        print(f"  Route-Stops: {status['route_stops_count']}")
        print(f"  Last Routes Update: {status['last_routes_update']}")
        print(f"  Last Stops Update: {status['last_stops_update']}")
        print(f"  Data is stale: {status['is_stale']}")
        return

    if args.routes:
        updater.update_routes()
    elif args.stops:
        updater.update_stops()
    elif args.route_stops:
        updater.update_route_stops(args.max_routes)
    elif args.all:
        updater.update_all_data(args.max_routes)
    else:
        print(
            "Please specify what to update: --routes, --stops, --route-stops, --all, or --status"
        )


if __name__ == "__main__":
    main()
