"""
Hong Kong KMB/LWB Bus API Connector
Integrates with KMB/LWB bus API for real-time data
Uses local database for routes and stops, only fetches ETA data from API
"""

import json
import logging
import time
from typing import Any, Optional

import pandas as pd
import requests
from database_manager import KMBDatabaseManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# HTTP status codes
HTTP_OK = 200


class HKTransportAPIs:
    """Main class to handle KMB/LWB transport API connections"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "HK-Transport-Dashboard/1.0",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        # KMB/LWB API endpoints only
        self.api_endpoints = {
            "kmb_lwb": {
                "base": "https://data.etabus.gov.hk/v1/transport/kmb",
                "routes": "https://data.etabus.gov.hk/v1/transport/kmb/route",
                "stops": "https://data.etabus.gov.hk/v1/transport/kmb/stop",
                "eta": "https://data.etabus.gov.hk/v1/transport/kmb/eta",
                "route_stop": "https://data.etabus.gov.hk/v1/transport/kmb/route-stop",
                "stop_eta": "https://data.etabus.gov.hk/v1/transport/kmb/stop-eta",
            }
        }

        # Cache for API responses
        self.cache = {}
        self.cache_timeout = 60  # seconds

    def _make_request(self, url: str, timeout: int = 10) -> Optional[dict[str, Any]]:
        """Make HTTP request with error handling"""
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"API request failed for {url}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error for {url}: {e}")
            return None

    def _get_cached_data(self, key: str) -> Optional[dict[str, Any]]:
        """Get cached data if not expired"""
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_timeout:
                return data
        return None

    def _cache_data(self, key: str, data: dict[str, Any]):
        """Cache data with timestamp"""
        self.cache[key] = (data, time.time())


class KMBLWBConnector:
    """KMB/LWB Bus API Connector using local database for routes/stops"""

    def __init__(self, db_path: str = "kmb_data.db"):
        self.base_url = "https://data.etabus.gov.hk/v1/transport/kmb"
        self.db_manager = KMBDatabaseManager(db_path)
        self.session = requests.Session()
        # Add proper headers for KMB API based on official documentation
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Referer": "https://data.etabus.gov.hk/",
                "Origin": "https://data.etabus.gov.hk",
            }
        )

    def get_routes(self) -> pd.DataFrame:
        """Get all KMB/LWB routes from local database"""
        try:
            return self.db_manager.get_routes()
        except Exception as e:
            logger.error(f"Error fetching KMB routes from database: {e}")
            return pd.DataFrame()

    def get_stops(self) -> pd.DataFrame:
        """Get all KMB/LWB stops from local database"""
        try:
            return self.db_manager.get_stops()
        except Exception as e:
            logger.error(f"Error fetching KMB stops from database: {e}")
            return pd.DataFrame()

    def get_route_stops(
        self, route_id: str, direction: int = 1, service_type: int = 1
    ) -> pd.DataFrame:
        """Get stops for a specific route from local database"""
        try:
            return self.db_manager.get_route_stops(route_id, direction, service_type)
        except Exception as e:
            logger.error(
                f"Error fetching KMB route stops for {route_id} from database: {e}"
            )
            return pd.DataFrame()

    def get_stop_eta(
        self, stop_id: str, route_id: Optional[str] = None
    ) -> pd.DataFrame:
        """Get ETA for a specific stop"""
        try:
            if route_id:
                url = f"{self.base_url}/stop-eta/{stop_id}/{route_id}"
            else:
                url = f"{self.base_url}/stop-eta/{stop_id}"

            params = {"lang": "en"}
            response = self.session.get(url, params=params, timeout=15)

            logger.info(f"KMB Stop ETA API Response Status: {response.status_code}")

            if response.status_code == HTTP_OK:
                data = response.json()

                if "data" in data:
                    etas = []
                    for eta in data["data"]:
                        etas.append(
                            {
                                "stop_id": stop_id,
                                "route_id": eta.get("route", ""),
                                "eta": eta.get("eta", ""),
                                "eta_seq": eta.get("eta_seq", ""),
                                "dest_en": eta.get("dest_en", ""),
                                "company": "KMB/LWB",
                            }
                        )
                    return pd.DataFrame(etas)
            else:
                logger.error(
                    f"KMB Stop ETA API failed with status {response.status_code}: {response.text}"
                )

        except Exception as e:
            logger.error(f"Error fetching KMB ETA for stop {stop_id}: {e}")

        # Return empty DataFrame if API fails
        return pd.DataFrame()


# Main KMB API Manager
class HKTransportAPIManager:
    """Main class to manage KMB/LWB transport API connections"""

    def __init__(self):
        self.kmb_lwb = KMBLWBConnector()

    def get_all_routes(self) -> dict[str, pd.DataFrame]:
        """Get routes from KMB/LWB"""
        return {"KMB/LWB": self.kmb_lwb.get_routes()}

    def get_all_stops(self) -> dict[str, pd.DataFrame]:
        """Get stops from KMB/LWB"""
        return {"KMB/LWB": self.kmb_lwb.get_stops()}

    def get_route_stops(
        self, route_id: str, direction: int = 1, service_type: int = 1
    ) -> pd.DataFrame:
        """Get stops for a specific KMB/LWB route, direction, and service type"""
        return self.kmb_lwb.get_route_stops(route_id, direction, service_type)

    def get_stop_eta(
        self, stop_id: str, route_id: Optional[str] = None
    ) -> pd.DataFrame:
        """Get ETA for a specific KMB/LWB stop"""
        return self.kmb_lwb.get_stop_eta(stop_id, route_id)

    def get_service_status(self) -> dict[str, Any]:
        """Get service status for KMB/LWB"""
        return {"KMB/LWB": {"status": "Normal Service"}}
