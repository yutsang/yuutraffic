"""
Hong Kong KMB/LWB Bus Database Manager
Manages SQLite database for KMB/LWB bus routes, stops, and route-stops data
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HONG_KONG_MIN_LAT = 22.15
HONG_KONG_MAX_LAT = 22.6
HONG_KONG_MIN_LNG = 113.8
HONG_KONG_MAX_LNG = 114.5


class KMBDatabaseManager:
    """Database manager for KMB routes and stops data"""

    def __init__(self, db_path: str = "kmb_data.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS routes (
                    route_id TEXT PRIMARY KEY,
                    route_name TEXT,
                    origin_en TEXT,
                    destination_en TEXT,
                    origin_tc TEXT,
                    destination_tc TEXT,
                    service_type INTEGER,
                    company TEXT DEFAULT 'KMB/LWB',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for col in ["origin_tc", "destination_tc"]:
                try:
                    cursor.execute(f"ALTER TABLE routes ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stops (
                    stop_id TEXT PRIMARY KEY,
                    stop_name_en TEXT,
                    stop_name_tc TEXT,
                    lat REAL,
                    lng REAL,
                    company TEXT DEFAULT 'KMB/LWB',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            try:
                cursor.execute("ALTER TABLE stops ADD COLUMN stop_name_tc TEXT")
            except sqlite3.OperationalError:
                pass

            cursor.execute("""
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
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS data_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    update_type TEXT,
                    records_updated INTEGER,
                    status TEXT,
                    error_message TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

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

    def insert_routes(self, routes_data: list[dict[str, Any]]) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            updated_count = 0
            for route in routes_data:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO routes
                    (route_id, route_name, origin_en, destination_en, origin_tc, destination_tc, service_type, company, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (
                        route.get("route"),
                        f"{route.get('orig_en', '')} → {route.get('dest_en', '')}"
                        or route.get("route"),  # route_name
                        route.get("orig_en"),
                        route.get("dest_en"),
                        route.get("orig_tc", "") or "",
                        route.get("dest_tc", "") or "",
                        route.get("service_type", 1),
                        "KMB/LWB",
                    ),
                )
                updated_count += 1
            conn.commit()
            logger.info(f"Inserted/updated {updated_count} routes")
            return updated_count

    def insert_stops(self, stops_data: list[dict[str, Any]]) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            updated_count = 0
            for stop in stops_data:
                lat = float(stop.get("lat", stop.get("latitude", 0)))
                lng = float(stop.get("long", stop.get("lng", 0)))
                if (
                    HONG_KONG_MIN_LAT <= lat <= HONG_KONG_MAX_LAT
                    and HONG_KONG_MIN_LNG <= lng <= HONG_KONG_MAX_LNG
                ):
                    stop_id = stop.get("stop", stop.get("stop_id", ""))
                    name_en = (
                        stop.get("name_en", stop.get("name", stop.get("nameEn", "")))
                        or ""
                    )
                    name_tc = stop.get("name_tc", stop.get("nameTc", "")) or ""
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO stops
                        (stop_id, stop_name_en, stop_name_tc, lat, lng, company, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                        (stop_id, name_en, name_tc, lat, lng, "KMB/LWB"),
                    )
                    updated_count += 1
            conn.commit()
            logger.info(f"Inserted/updated {updated_count} stops")
            return updated_count

    def insert_route_stops(self, route_stops_data: list[dict[str, Any]]) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            updated_count = 0
            for route_stop in route_stops_data:
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
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(
                """
                SELECT route_id, route_name, origin_en as origin, destination_en as destination,
                       service_type, company FROM routes ORDER BY route_id
                """,
                conn,
            )

    def get_stops(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(
                """
                SELECT stop_id, stop_name_en as stop_name, lat, lng, company
                FROM stops ORDER BY stop_id
                """,
                conn,
            )

    def get_route_stops(
        self, route_id: str, direction: int = 1, service_type: int = 1
    ) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(
                """
                SELECT rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                       s.lat, s.lng, rs.sequence, s.company
                FROM route_stops rs
                JOIN stops s ON rs.stop_id = s.stop_id
                WHERE rs.route_id = ? AND rs.direction = ? AND rs.service_type = ?
                ORDER BY rs.sequence
                """,
                conn,
                params=(route_id, direction, service_type),
            )

    def get_database_stats(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM routes")
            stats = {"routes_count": cursor.fetchone()[0]}
            cursor.execute("SELECT COUNT(*) FROM stops")
            stats["stops_count"] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM route_stops")
            stats["route_stops_count"] = cursor.fetchone()[0]
            cursor.execute("SELECT MAX(updated_at) FROM routes")
            stats["last_routes_update"] = cursor.fetchone()[0]
            cursor.execute("SELECT MAX(updated_at) FROM stops")
            stats["last_stops_update"] = cursor.fetchone()[0]
            return stats

    def is_data_stale(self, max_age_hours: int = 24) -> bool:
        stats = self.get_database_stats()
        if stats["routes_count"] == 0 or stats["stops_count"] == 0:
            return True
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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO data_updates (update_type, records_updated, status, error_message)
                VALUES (?, ?, ?, ?)
            """,
                (update_type, records_updated, status, error_message),
            )
            conn.commit()
