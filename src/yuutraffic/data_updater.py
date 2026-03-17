"""
Hong Kong KMB/LWB Bus Data Updater
Updates local database with routes, stops, and route-stops data from KMB/LWB API
"""

import argparse
import logging
import sys
import time
from typing import Any, Optional

import requests

from .database_manager import KMBDatabaseManager

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
        self.db_manager = KMBDatabaseManager(db_path)
        self.base_url = "https://data.etabus.gov.hk/v1/transport/kmb"
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "KMB-Dashboard/1.0", "Accept": "application/json"}
        )

    def fetch_routes(self) -> list[dict[str, Any]]:
        try:
            logger.info("Fetching KMB routes from API...")
            url = f"{self.base_url}/route"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            if "data" in data:
                logger.info(f"Fetched {len(data['data'])} routes")
                return data["data"]
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching routes: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching routes: {e}")
            return []

    def fetch_stops(self) -> list[dict[str, Any]]:
        try:
            logger.info("Fetching KMB stops from API...")
            url = f"{self.base_url}/stop"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            if "data" in data:
                logger.info(f"Fetched {len(data['data'])} stops")
                return data["data"]
            return []
        except requests.exceptions.HTTPError as e:
            if (
                getattr(e, "response", None)
                and getattr(e.response, "status_code", None) == 403
            ):
                logger.warning(
                    "Stops API 403 (may be geo-restricted); using existing stops data"
                )
            else:
                logger.error(f"Error fetching stops: {e}")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching stops: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching stops: {e}")
            return []

    def fetch_route_stops(
        self, route_id: str, direction: str = "O", service_type: int = 1
    ) -> list[dict[str, Any]]:
        try:
            url = f"{self.base_url}/route-stop/{route_id}/{direction}/{service_type}"
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            logger.warning(f"Error fetching route stops for {route_id}: {e}")
            return []

    def fetch_all_route_stops(
        self, routes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        all_route_stops = []
        for i, route in enumerate(routes):
            route_id = route.get("route") or route.get("route_id")
            if not route_id:
                continue
            for direction_bound in ["O", "I"]:
                route_stops = self.fetch_route_stops(route_id, direction_bound)
                for rs in route_stops:
                    rs["route"] = route_id
                    rs["bound"] = direction_bound
                    all_route_stops.append(rs)
                time.sleep(0.1)
            if (i + 1) % 50 == 0:
                logger.info(f"Processed {i + 1}/{len(routes)} routes")
        return all_route_stops

    def update_routes(self) -> bool:
        try:
            routes = self.fetch_routes()
            if not routes:
                self.db_manager.log_update(
                    "routes", 0, "error", "No routes data fetched"
                )
                return False
            updated = self.db_manager.insert_routes(routes)
            self.db_manager.log_update("routes", updated, "success")
            return True
        except Exception as e:
            self.db_manager.log_update("routes", 0, "error", str(e))
            return False

    def update_stops(self) -> bool:
        try:
            stops = self.fetch_stops()
            if not stops:
                self.db_manager.log_update("stops", 0, "error", "No stops data fetched")
                return False
            updated = self.db_manager.insert_stops(stops)
            self.db_manager.log_update("stops", updated, "success")
            return True
        except Exception as e:
            self.db_manager.log_update("stops", 0, "error", str(e))
            return False

    def update_route_stops(self, max_routes: Optional[int] = None) -> bool:
        try:
            routes_df = self.db_manager.get_routes()
            if routes_df.empty:
                self.db_manager.log_update(
                    "route_stops", 0, "error", "No routes in database"
                )
                return False
            routes = routes_df.to_dict("records")
            if max_routes:
                routes = routes[:max_routes]
            route_stops = self.fetch_all_route_stops(routes)
            if not route_stops:
                self.db_manager.log_update(
                    "route_stops", 0, "error", "No route-stops data fetched"
                )
                return False
            updated = self.db_manager.insert_route_stops(route_stops)
            self.db_manager.log_update("route_stops", updated, "success")
            return True
        except Exception as e:
            self.db_manager.log_update("route_stops", 0, "error", str(e))
            return False

    def update_all_data(self, max_routes: Optional[int] = None) -> bool:
        success = True
        if not self.update_routes():
            success = False
        if not self.update_stops():
            success = False
        if not self.update_route_stops(max_routes):
            success = False
        return success

    def get_update_status(self) -> dict[str, Any]:
        stats = self.db_manager.get_database_stats()
        return {
            **stats,
            "is_stale": self.db_manager.is_data_stale(),
        }


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Update KMB transportation data")
    parser.add_argument("--routes", action="store_true")
    parser.add_argument("--stops", action="store_true")
    parser.add_argument("--route-stops", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--max-routes", type=int)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--db-path", default="data/01_raw/kmb_data.db")
    args = parser.parse_args()

    updater = KMBDataUpdater(args.db_path)

    if args.status:
        status = updater.get_update_status()
        for k, v in status.items():
            logging.info(f"  {k}: {v}")
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
        logging.error("Specify: --routes, --stops, --route-stops, --all, or --status")


if __name__ == "__main__":
    main()
