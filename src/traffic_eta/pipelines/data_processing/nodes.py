"""
This is a boilerplate pipeline 'data_processing'
generated using Kedro 0.19.14
"""

import logging
from typing import Any

import pandas as pd
from database_manager import KMBDatabaseManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for Hong Kong boundaries
HONG_KONG_MIN_LAT = 22.15
HONG_KONG_MAX_LAT = 22.6
HONG_KONG_MIN_LNG = 113.8
HONG_KONG_MAX_LNG = 114.5

# Constants for validation thresholds
MIN_ROUTES_COUNT = 100
MIN_STOPS_COUNT = 1000
MIN_ROUTE_STOPS_COUNT = 5000


def process_routes_data(routes_df: pd.DataFrame) -> pd.DataFrame:
    """
    Process and store routes data in the database

    Args:
        routes_df: DataFrame containing routes data

    Returns:
        Processed routes DataFrame
    """
    try:
        db_manager = KMBDatabaseManager()

        # Clean and transform routes data
        processed_routes = []
        for _, row in routes_df.iterrows():
            processed_route = {
                "route": row["route"],
                "dest_en": row["dest_en"],
                "orig_en": row["orig_en"],
                "service_type": row["service_type"],
            }

            # Only include routes with valid data
            if processed_route["route"] and processed_route["dest_en"]:
                processed_routes.append(processed_route)

        # Store in database
        count = db_manager.insert_routes(processed_routes)
        logger.info(f"Processed and stored {count} routes")
        return routes_df

    except Exception as e:
        logger.error(f"Error processing routes data: {e}")
        return routes_df


def process_stops_data(stops_df: pd.DataFrame) -> pd.DataFrame:
    """
    Process and store stops data in the database

    Args:
        stops_df: DataFrame containing stops data

    Returns:
        Processed stops DataFrame
    """
    try:
        db_manager = KMBDatabaseManager()

        # Clean and transform stops data
        processed_stops = []
        for _, row in stops_df.iterrows():
            # Validate coordinates
            try:
                lat = float(row["lat"])
                lng = float(row["long"])

                # Only include stops with valid coordinates in Hong Kong
                if validate_location_data(lat, lng):
                    processed_stop = {
                        "stop": row["stop"],
                        "name_en": row["name_en"],
                        "lat": lat,
                        "long": lng,
                    }

                    if processed_stop["stop"] and processed_stop["name_en"]:
                        processed_stops.append(processed_stop)

            except (ValueError, TypeError):
                continue

        # Store in database
        count = db_manager.insert_stops(processed_stops)
        logger.info(f"Processed and stored {count} stops")
        return stops_df

    except Exception as e:
        logger.error(f"Error processing stops data: {e}")
        return stops_df


def validate_location_data(lat: float, lng: float) -> bool:
    """Validate location coordinates are within Hong Kong bounds."""
    # Hong Kong bounds: 22.15-22.6°N, 113.8-114.5°E
    return (
        HONG_KONG_MIN_LAT <= lat <= HONG_KONG_MAX_LAT
        and HONG_KONG_MIN_LNG <= lng <= HONG_KONG_MAX_LNG
    )


def process_route_stops_data(route_stops_df: pd.DataFrame) -> pd.DataFrame:
    """
    Process and store route-stops mapping data in the database

    Args:
        route_stops_df: DataFrame containing route-stops data

    Returns:
        Processed route-stops DataFrame
    """
    try:
        db_manager = KMBDatabaseManager()

        # Clean and transform route-stops data
        processed_route_stops = []
        for _, row in route_stops_df.iterrows():
            processed_route_stop = {
                "route": row["route"],
                "stop": row["stop"],
                "bound": row["bound"],
                "seq": row["seq"],
                "service_type": row["service_type"],
            }

            # Only include valid mappings
            if processed_route_stop["route"] and processed_route_stop["stop"]:
                processed_route_stops.append(processed_route_stop)

        # Store in database
        count = db_manager.insert_route_stops(processed_route_stops)
        logger.info(f"Processed and stored {count} route-stop mappings")
        return route_stops_df

    except Exception as e:
        logger.error(f"Error processing route-stops data: {e}")
        return route_stops_df


def validate_database_integrity() -> dict[str, Any]:
    """
    Validate the integrity of the processed data in the database

    Returns:
        Dictionary with validation results
    """
    try:
        db_manager = KMBDatabaseManager()
        stats = db_manager.get_database_stats()

        # Basic validation checks
        validation_results = {
            "routes_count": stats["routes_count"],
            "stops_count": stats["stops_count"],
            "route_stops_count": stats["route_stops_count"],
            "is_valid": True,
            "issues": [],
        }

        # Check if we have reasonable data
        if stats["routes_count"] < MIN_ROUTES_COUNT:
            validation_results["issues"].append(
                f"Low route count: {stats['routes_count']}"
            )

        if stats["stops_count"] < MIN_STOPS_COUNT:
            validation_results["issues"].append(
                f"Low stop count: {stats['stops_count']}"
            )

        if stats["route_stops_count"] < MIN_ROUTE_STOPS_COUNT:
            validation_results["issues"].append(
                f"Low route-stop count: {stats['route_stops_count']}"
            )

        # Check for orphaned route-stops
        orphaned_check = db_manager.check_data_integrity()
        if orphaned_check["orphaned_route_stops"] > 0:
            validation_results["issues"].append(
                f"Found {orphaned_check['orphaned_route_stops']} orphaned route-stops"
            )

        if validation_results["issues"]:
            validation_results["is_valid"] = False

        logger.info(
            f"Database validation completed. Valid: {validation_results['is_valid']}"
        )
        return validation_results

    except Exception as e:
        logger.error(f"Error validating database: {e}")
        return {"is_valid": False, "error": str(e)}


def create_sample_data_for_testing() -> dict[str, Any]:
    """
    Create sample data for testing when API is unavailable

    Returns:
        Dictionary with sample data counts
    """
    try:
        db_manager = KMBDatabaseManager()

        # Sample routes (including 219X, 24, 65X that user mentioned)
        sample_routes = [
            {
                "route": "65X",
                "dest_en": "Tsim Sha Tsui (Circular)",
                "orig_en": "Tin Shui Wai (Tin Yiu Bus Terminus)",
                "service_type": 1,
            },
            {
                "route": "219X",
                "dest_en": "Tsim Sha Tsui (Circular)",
                "orig_en": "Ko Ling Road",
                "service_type": 1,
            },
            {
                "route": "24",
                "dest_en": "Mong Kok (Circular)",
                "orig_en": "Kai Yip",
                "service_type": 1,
            },
            {
                "route": "E23",
                "dest_en": "Airport (Ground Transportation Centre)",
                "orig_en": "Tsim Sha Tsui East",
                "service_type": 1,
            },
            {
                "route": "41A",
                "dest_en": "Tsim Sha Tsui East",
                "orig_en": "Ma On Shan (Heng On)",
                "service_type": 1,
            },
        ]

        # Sample stops
        sample_stops = [
            {
                "stop": "STOP_TST_001",
                "name_en": "Tsim Sha Tsui (Nathan Road)",
                "lat": 22.2976,
                "long": 114.1697,
            },
            {
                "stop": "STOP_TSW_001",
                "name_en": "Tin Shui Wai Station",
                "lat": 22.4578,
                "long": 113.9938,
            },
            {
                "stop": "STOP_MK_001",
                "name_en": "Mong Kok (Argyle Street)",
                "lat": 22.3193,
                "long": 114.1694,
            },
            {
                "stop": "STOP_AP_001",
                "name_en": "Airport Terminal 1",
                "lat": 22.3080,
                "long": 113.9185,
            },
        ]

        # Sample route-stops
        sample_route_stops = [
            {
                "route": "65X",
                "stop": "STOP_TSW_001",
                "bound": "O",
                "seq": 1,
                "service_type": 1,
            },
            {
                "route": "65X",
                "stop": "STOP_TST_001",
                "bound": "O",
                "seq": 2,
                "service_type": 1,
            },
            {
                "route": "219X",
                "stop": "STOP_TST_001",
                "bound": "O",
                "seq": 1,
                "service_type": 1,
            },
            {
                "route": "24",
                "stop": "STOP_MK_001",
                "bound": "O",
                "seq": 1,
                "service_type": 1,
            },
        ]

        # Insert sample data
        routes_count = db_manager.insert_routes(sample_routes)
        stops_count = db_manager.insert_stops(sample_stops)
        route_stops_count = db_manager.insert_route_stops(sample_route_stops)

        logger.info(
            f"Created sample data: {routes_count} routes, {stops_count} stops, {route_stops_count} route-stops"
        )

        return {
            "routes_count": routes_count,
            "stops_count": stops_count,
            "route_stops_count": route_stops_count,
            "success": True,
        }

    except Exception as e:
        logger.error(f"Error creating sample data: {e}")
        return {"success": False, "error": str(e)}


def create_route_summary(
    routes_df: pd.DataFrame, route_stops_df: pd.DataFrame
) -> pd.DataFrame:
    """Create route summary statistics."""
    # ... existing code ...


def validate_data_quality(df: pd.DataFrame, min_records: int = 100) -> bool:
    """Validate data quality metrics."""
    # ... existing code ...


def create_stop_summary(
    stops_df: pd.DataFrame, route_stops_df: pd.DataFrame
) -> dict[str, Any]:
    """Create stop summary statistics."""
    # ... existing code ...
