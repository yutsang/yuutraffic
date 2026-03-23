"""
Database Manager for KMB Transportation Data

This module handles local storage of KMB routes and stops data using SQLite.
Only ETA data is fetched from the API in real-time.
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KMBDatabaseManager:
    """Database manager for KMB routes and stops data"""

    def __init__(self, db_path: str = "kmb_data.db"):
        """
        Initialize the database manager

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create routes table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS routes (
                    route_id TEXT PRIMARY KEY,
                    route_name TEXT,
                    origin_en TEXT,
                    destination_en TEXT,
                    service_type INTEGER,
                    company TEXT DEFAULT 'KMB/LWB',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Create stops table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS stops (
                    stop_id TEXT PRIMARY KEY,
                    stop_name_en TEXT,
                    lat REAL,
                    lng REAL,
                    company TEXT DEFAULT 'KMB/LWB',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Create route_stops table (junction table)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS route_stops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route_id TEXT,
                    stop_id TEXT,
                    direction INTEGER,
                    service_type INTEGER,
                    sequence INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (route_id) REFERENCES routes (route_id),
                    FOREIGN KEY (stop_id) REFERENCES stops (stop_id),
                    UNIQUE(route_id, stop_id, direction, service_type)
                )
            """
            )

            # Create data_updates table to track update history
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS data_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    update_type TEXT,
                    records_updated INTEGER,
                    status TEXT,
                    error_message TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Create indexes for better performance
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_routes_route_id ON routes(route_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_stops_stop_id ON stops(stop_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_route_stops_route_id ON route_stops(route_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_route_stops_stop_id ON route_stops(stop_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_route_stops_direction ON route_stops(direction)"
            )

            conn.commit()
            logger.info("Database initialized successfully")

    def insert_routes(self, routes_data: List[Dict]) -> int:
        """
        Insert or update routes data

        Args:
            routes_data: List of route dictionaries

        Returns:
            Number of routes inserted/updated
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            updated_count = 0
            for route in routes_data:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO routes 
                    (route_id, route_name, origin_en, destination_en, service_type, company, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (
                        route.get("route"),
                        route.get("dest_en"),
                        route.get("orig_en"),
                        route.get("dest_en"),
                        route.get("service_type", 1),
                        "KMB/LWB",
                    ),
                )
                updated_count += 1

            conn.commit()
            logger.info(f"Inserted/updated {updated_count} routes")
            return updated_count

    def insert_stops(self, stops_data: List[Dict]) -> int:
        """
        Insert or update stops data

        Args:
            stops_data: List of stop dictionaries

        Returns:
            Number of stops inserted/updated
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            updated_count = 0
            for stop in stops_data:
                # Only insert stops within Hong Kong boundaries
                lat = float(stop.get("lat", 0))
                lng = float(stop.get("long", 0))

                if 22.15 <= lat <= 22.6 and 113.8 <= lng <= 114.5:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO stops 
                        (stop_id, stop_name_en, lat, lng, company, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                        (stop.get("stop"), stop.get("name_en"), lat, lng, "KMB/LWB"),
                    )
                    updated_count += 1

            conn.commit()
            logger.info(f"Inserted/updated {updated_count} stops")
            return updated_count

    def insert_route_stops(self, route_stops_data: List[Dict]) -> int:
        """
        Insert or update route-stops mapping data

        Args:
            route_stops_data: List of route-stop dictionaries

        Returns:
            Number of route-stops inserted/updated
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            updated_count = 0
            for route_stop in route_stops_data:
                # Convert bound to numeric direction (O=1, I=2)
                bound = route_stop.get("bound", "O")
                direction = 1 if bound == "O" else 2

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO route_stops 
                    (route_id, stop_id, direction, service_type, sequence, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (
                        route_stop.get("route"),
                        route_stop.get("stop"),
                        direction,
                        route_stop.get("service_type", 1),
                        route_stop.get("seq", 0),
                    ),
                )
                updated_count += 1

            conn.commit()
            logger.info(f"Inserted/updated {updated_count} route-stops")
            return updated_count

    def get_routes(self) -> pd.DataFrame:
        """
        Get all routes from database

        Returns:
            DataFrame with route data
        """
        with sqlite3.connect(self.db_path) as conn:
            query = """
                SELECT 
                    route_id,
                    route_name,
                    origin_en as origin,
                    destination_en as destination,
                    service_type,
                    company
                FROM routes
                ORDER BY route_id
            """
            return pd.read_sql_query(query, conn)

    def get_stops(self) -> pd.DataFrame:
        """
        Get all stops from database

        Returns:
            DataFrame with stop data
        """
        with sqlite3.connect(self.db_path) as conn:
            query = """
                SELECT 
                    stop_id,
                    stop_name_en as stop_name,
                    lat,
                    lng,
                    company
                FROM stops
                ORDER BY stop_id
            """
            return pd.read_sql_query(query, conn)

    def get_route_stops(
        self, route_id: str, direction: int = 1, service_type: int = 1
    ) -> pd.DataFrame:
        """
        Get stops for a specific route

        Args:
            route_id: Route identifier
            direction: Route direction (1 or 2)
            service_type: Service type (usually 1)

        Returns:
            DataFrame with route stops data
        """
        with sqlite3.connect(self.db_path) as conn:
            query = """
                SELECT 
                    rs.route_id,
                    rs.stop_id,
                    s.stop_name_en as stop_name,
                    s.lat,
                    s.lng,
                    rs.sequence,
                    s.company
                FROM route_stops rs
                JOIN stops s ON rs.stop_id = s.stop_id
                WHERE rs.route_id = ? AND rs.direction = ? AND rs.service_type = ?
                ORDER BY rs.sequence
            """
            return pd.read_sql_query(
                query, conn, params=(route_id, direction, service_type)
            )

    def get_database_stats(self) -> Dict:
        """
        Get database statistics

        Returns:
            Dictionary with database statistics
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            stats = {}

            # Count routes
            cursor.execute("SELECT COUNT(*) FROM routes")
            stats["routes_count"] = cursor.fetchone()[0]

            # Count stops
            cursor.execute("SELECT COUNT(*) FROM stops")
            stats["stops_count"] = cursor.fetchone()[0]

            # Count route-stops
            cursor.execute("SELECT COUNT(*) FROM route_stops")
            stats["route_stops_count"] = cursor.fetchone()[0]

            # Last update times
            cursor.execute("SELECT MAX(updated_at) FROM routes")
            stats["last_routes_update"] = cursor.fetchone()[0]

            cursor.execute("SELECT MAX(updated_at) FROM stops")
            stats["last_stops_update"] = cursor.fetchone()[0]

            return stats

    def is_data_stale(self, max_age_hours: int = 24) -> bool:
        """
        Check if database data is stale

        Args:
            max_age_hours: Maximum age in hours before data is considered stale

        Returns:
            True if data is stale, False otherwise
        """
        stats = self.get_database_stats()

        # Check if we have any data
        if stats["routes_count"] == 0 or stats["stops_count"] == 0:
            return True

        # Check last update time
        last_update = stats.get("last_routes_update")
        if last_update:
            last_update_time = datetime.fromisoformat(last_update)
            return datetime.now() - last_update_time > timedelta(hours=max_age_hours)

        return True

    def log_update(
        self,
        update_type: str,
        records_updated: int,
        status: str,
        error_message: Optional[str] = None,
    ):
        """
        Log an update operation

        Args:
            update_type: Type of update (routes, stops, route_stops)
            records_updated: Number of records updated
            status: Update status (success, error)
            error_message: Error message if any
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO data_updates (update_type, records_updated, status, error_message)
                VALUES (?, ?, ?, ?)
            """,
                (update_type, records_updated, status, error_message),
            )
            conn.commit()

    def get_update_history(self, limit: int = 10) -> pd.DataFrame:
        """
        Get update history

        Args:
            limit: Maximum number of records to return

        Returns:
            DataFrame with update history
        """
        with sqlite3.connect(self.db_path) as conn:
            query = """
                SELECT * FROM data_updates
                ORDER BY updated_at DESC
                LIMIT ?
            """
            return pd.read_sql_query(query, conn, params=(limit,))

    def cleanup_old_data(self, days_to_keep: int = 30):
        """
        Clean up old update logs

        Args:
            days_to_keep: Number of days of logs to keep
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM data_updates 
                WHERE updated_at < datetime('now', '-{} days')
            """.format(
                    days_to_keep
                )
            )
            conn.commit()
            logger.info(f"Cleaned up update logs older than {days_to_keep} days")
