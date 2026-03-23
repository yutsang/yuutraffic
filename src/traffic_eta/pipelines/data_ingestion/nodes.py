"""
This is a boilerplate pipeline 'data_ingestion'
generated using Kedro 0.19.14
"""

import logging
import time
from typing import Any

import pandas as pd
import requests

# Hong Kong geographic bounds constants
HK_MIN_LAT = 22.15
HK_MAX_LAT = 22.6
HK_MIN_LNG = 113.8
HK_MAX_LNG = 114.5

# API constants
HTTP_OK_STATUS = 200

logger = logging.getLogger(__name__)


def fetch_kmb_routes() -> list[dict[str, Any]]:
    """
    Fetch all KMB routes from the official API

    Returns:
        List of route dictionaries
    """
    try:
        url = "https://data.etabus.gov.hk/v1/transport/kmb/route"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data["type"] == "RouteList":
            routes = data["data"]
            logger.info(f"Successfully fetched {len(routes)} routes from KMB API")
            return routes
        else:
            logger.error(f"Unexpected API response type: {data.get('type')}")
            return []

    except Exception as e:
        logger.error(f"Error fetching KMB routes: {e}")
        return []


def fetch_kmb_stops() -> list[dict[str, Any]]:
    """
    Fetch all KMB stops from the official API

    Returns:
        List of stop dictionaries
    """
    try:
        url = "https://data.etabus.gov.hk/v1/transport/kmb/stop"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data["type"] == "StopList":
            stops = data["data"]
            # Filter to Hong Kong area only
            hk_stops = []
            for stop in stops:
                lat = float(stop.get("lat", 0))
                lng = float(stop.get("long", 0))
                if HK_MIN_LAT <= lat <= HK_MAX_LAT and HK_MIN_LNG <= lng <= HK_MAX_LNG:
                    hk_stops.append(stop)

            logger.info(f"Successfully fetched {len(hk_stops)} HK stops from KMB API")
            return hk_stops
        else:
            logger.error(f"Unexpected API response type: {data.get('type')}")
            return []

    except Exception as e:
        logger.error(f"Error fetching KMB stops: {e}")
        return []


def fetch_route_stops_sample(
    routes: list[dict[str, Any]], max_routes: int = 50
) -> list[dict[str, Any]]:
    """
    Fetch route-stop mappings for a sample of routes

    Args:
        routes: List of route dictionaries
        max_routes: Maximum number of routes to process

    Returns:
        List of route-stop mapping dictionaries
    """
    try:
        route_stops = []
        processed = 0

        for route in routes[:max_routes]:
            route_id = route["route"]
            service_type = route.get("service_type", 1)

            # Fetch for both directions
            for bound in ["O", "I"]:  # Outbound, Inbound
                try:
                    url = f"https://data.etabus.gov.hk/v1/transport/kmb/route-stop/{route_id}/{bound}/{service_type}"

                    response = requests.get(url, timeout=10)
                    if response.status_code == HTTP_OK_STATUS:
                        data = response.json()
                        if data["type"] == "RouteStopList" and data["data"]:
                            route_stops.extend(data["data"])

                    # Small delay to avoid overwhelming the API
                    time.sleep(0.1)

                except Exception as e:
                    logger.warning(
                        f"Error fetching route-stops for {route_id}-{bound}: {e}"
                    )
                    continue

            processed += 1
            if processed % 10 == 0:
                logger.info(f"Processed {processed}/{max_routes} routes...")

        logger.info(f"Successfully fetched {len(route_stops)} route-stop mappings")
        return route_stops

    except Exception as e:
        logger.error(f"Error fetching route-stops: {e}")
        return []


def validate_location_data(lat: float, lng: float) -> bool:
    """Validate location coordinates are within Hong Kong bounds."""
    # Hong Kong bounds: 22.15-22.6°N, 113.8-114.5°E
    return HK_MIN_LAT <= lat <= HK_MAX_LAT and HK_MIN_LNG <= lng <= HK_MAX_LNG


def process_route_data(routes_data: list[dict[str, Any]]) -> pd.DataFrame:
    """Process raw route data into a structured DataFrame."""
    # ... existing code ...


def process_stop_data(stops_data: list[dict[str, Any]]) -> pd.DataFrame:
    """Process raw stop data into a structured DataFrame."""
    # ... existing code ...


def validate_api_response(response: requests.Response) -> bool:
    """Validate API response status and content."""
    if response.status_code != HTTP_OK_STATUS:
        logger.error(f"API request failed with status {response.status_code}")
        return False

    try:
        data = response.json()
        if not isinstance(data, dict) or "data" not in data:
            logger.error("Invalid API response format")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to parse API response: {e}")
        return False
