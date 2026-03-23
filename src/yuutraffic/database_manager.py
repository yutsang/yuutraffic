"""
Hong Kong Bus Database Manager
Manages SQLite database for KMB/LWB, Citybus (CTB), and other bus routes
"""

import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

HONG_KONG_MIN_LAT = 22.15
HONG_KONG_MAX_LAT = 22.6
HONG_KONG_MIN_LNG = 113.8
HONG_KONG_MAX_LNG = 114.5


def route_key(company: str, route_id: str) -> str:
    """Internal lookup key: KMB_65X, CTB_1, GMB_HKI-1, MTRB_K12. Avoids clashes across operators."""
    c = str(company).strip().upper()
    rid = str(route_id).strip()
    if c.startswith("KMB") or "LWB" in c:
        prefix = "KMB"
    elif c.startswith("CTB"):
        prefix = "CTB"
    elif c.startswith("GMB") or "GREEN" in c and "MINIBUS" in c:
        prefix = "GMB"
    elif "MTR" in c and "BUS" in c:
        prefix = "MTRB"
    elif c.startswith("RMB") or ("RED" in c and "MINIBUS" in c):
        prefix = "RMB"
    else:
        prefix = "KMB"
    if rid.startswith(f"{prefix}_"):
        return rid
    return f"{prefix}_{rid}"


class KMBDatabaseManager:
    """Database manager for KMB routes and stops data"""

    def __init__(self, db_path: str = "kmb_data.db", init_db: bool = True):
        self.db_path = db_path
        if init_db:
            self.init_database()

    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            try:
                cursor.execute("PRAGMA table_info(routes)")
                route_cols = {row[1] for row in cursor.fetchall()}
            except sqlite3.OperationalError:
                route_cols = set()

            if not route_cols:
                cursor.execute("""
                    CREATE TABLE routes (
                        route_key TEXT PRIMARY KEY,
                        route_id TEXT NOT NULL,
                        route_name TEXT,
                        origin_en TEXT,
                        destination_en TEXT,
                        origin_tc TEXT,
                        destination_tc TEXT,
                        service_type INTEGER,
                        company TEXT DEFAULT 'KMB/LWB',
                        provider_route_id TEXT,
                        geometry_hash TEXT,
                        last_precomputed_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """)
            elif "route_key" not in route_cols:
                cursor.execute("ALTER TABLE routes RENAME TO routes_old")
                cursor.execute("""
                    CREATE TABLE routes (
                        route_key TEXT PRIMARY KEY,
                        route_id TEXT NOT NULL,
                        route_name TEXT,
                        origin_en TEXT,
                        destination_en TEXT,
                        origin_tc TEXT,
                        destination_tc TEXT,
                        service_type INTEGER,
                        company TEXT DEFAULT 'KMB/LWB',
                        provider_route_id TEXT,
                        geometry_hash TEXT,
                        last_precomputed_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """)
                cursor.execute("""
                    INSERT OR REPLACE INTO routes
                    (route_key, route_id, route_name, origin_en, destination_en, origin_tc, destination_tc, service_type, company, created_at, updated_at)
                    SELECT 'KMB_' || route_id, route_id, route_name, origin_en, destination_en,
                           COALESCE(origin_tc,''), COALESCE(destination_tc,''), service_type, COALESCE(company,'KMB/LWB'), created_at, updated_at
                    FROM routes_old
                    """)
                cursor.execute("DROP TABLE routes_old")
                # Migrate route_stops to use route_key
                try:
                    cursor.execute("PRAGMA table_info(route_stops)")
                    rs_cols = {row[1] for row in cursor.fetchall()}
                    if "route_key" not in rs_cols and "route_id" in rs_cols:
                        cursor.execute(
                            "ALTER TABLE route_stops ADD COLUMN route_key TEXT"
                        )
                        cursor.execute(
                            "UPDATE route_stops SET route_key = 'KMB_' || route_id WHERE route_key IS NULL OR route_key = ''"
                        )
                except sqlite3.OperationalError:
                    pass

            for col in [
                "origin_tc",
                "destination_tc",
                "geometry_hash",
                "last_precomputed_at",
                "provider_route_id",
            ]:
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
                    route_key TEXT,
                    route_id TEXT,
                    stop_id TEXT,
                    direction INTEGER,
                    service_type INTEGER,
                    sequence INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (route_key) REFERENCES routes (route_key),
                    FOREIGN KEY (stop_id) REFERENCES stops (stop_id),
                    UNIQUE(route_key, stop_id, direction, service_type)
                )
            """)
            try:
                cursor.execute("ALTER TABLE route_stops ADD COLUMN route_key TEXT")
            except sqlite3.OperationalError:
                pass

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS route_geometry (
                    route_key TEXT,
                    direction INTEGER,
                    geometry_hash TEXT,
                    last_precomputed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (route_key, direction)
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
            logger.debug("Database initialized successfully")

    def _ensure_route_geometry_table(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS route_geometry (
                route_key TEXT,
                direction INTEGER,
                geometry_hash TEXT,
                last_precomputed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (route_key, direction)
            )
            """)

    def insert_routes(
        self, routes_data: list[dict[str, Any]], company: str = "KMB/LWB"
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            updated_count = 0
            for route in routes_data:
                route_id = str(
                    route.get("route") or route.get("route_id") or ""
                ).strip()
                if not route_id:
                    continue
                rk = route_key(company, route_id)
                route_name = (
                    f"{route.get('orig_en', '')} → {route.get('dest_en', '')}"
                    or route_id
                )
                prov = route.get("provider_route_id")
                prov = (
                    str(prov).strip()
                    if prov is not None and str(prov).strip()
                    else None
                )
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO routes
                    (route_key, route_id, route_name, origin_en, destination_en, origin_tc, destination_tc, service_type, company, provider_route_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (
                        rk,
                        route_id,
                        route_name,
                        route.get("orig_en", ""),
                        route.get("dest_en", ""),
                        route.get("orig_tc", "") or "",
                        route.get("dest_tc", "") or "",
                        route.get("service_type", 1),
                        company,
                        prov,
                    ),
                )
                updated_count += 1
            conn.commit()
            logger.info(f"Inserted/updated {updated_count} routes")
            return updated_count

    def insert_stops(
        self,
        stops_data: list[dict[str, Any]],
        company: str = "KMB/LWB",
        require_hk_bounds: bool = True,
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            updated_count = 0
            for stop in stops_data:
                lat = float(stop.get("lat", stop.get("latitude", 0)))
                lng = float(stop.get("long", stop.get("lng", 0)))
                in_hk = (
                    HONG_KONG_MIN_LAT <= lat <= HONG_KONG_MAX_LAT
                    and HONG_KONG_MIN_LNG <= lng <= HONG_KONG_MAX_LNG
                )
                if require_hk_bounds and not in_hk:
                    continue
                stop_id = stop.get("stop", stop.get("stop_id", ""))
                name_en = (
                    stop.get("name_en", stop.get("name", stop.get("nameEn", ""))) or ""
                )
                name_tc = stop.get("name_tc", stop.get("nameTc", "")) or ""
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO stops
                    (stop_id, stop_name_en, stop_name_tc, lat, lng, company, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (stop_id, name_en, name_tc, lat, lng, company),
                )
                updated_count += 1
            conn.commit()
            logger.info(f"Inserted/updated {updated_count} stops")
            return updated_count

    def insert_route_stops(
        self,
        route_stops_data: list[dict[str, Any]],
        company: str = "KMB/LWB",
        route_key_fn: Callable[[dict], str] | None = None,
    ) -> int:
        import hashlib

        # Group by route key to calculate hashes
        by_route_dir: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for rs in route_stops_data:
            rk = (
                route_key_fn(rs)
                if route_key_fn
                else route_key(company, rs.get("route", ""))
            )
            bound = rs.get("bound", "O")
            direction = 1 if str(bound).upper() in ("O", "1") else 2
            key = (rk, direction)
            if key not in by_route_dir:
                by_route_dir[key] = []
            by_route_dir[key].append(rs)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            updated_count = 0
            self._ensure_route_geometry_table(conn)

            for (rk, direction), stops in by_route_dir.items():
                # Sort stops by sequence to ensure consistent hash
                stops.sort(key=lambda s: int(s.get("seq", s.get("sequence", 0))))

                # Calculate new hash
                data = ",".join(
                    f"{s.get('stop') or s.get('stop_id')}:{s.get('seq') or s.get('sequence')}"
                    for s in stops
                )
                new_hash = hashlib.sha256(data.encode()).hexdigest()[:16]

                # Check current hash in DB
                cursor.execute(
                    "SELECT geometry_hash FROM route_geometry WHERE route_key = ? AND direction = ?",
                    (rk, direction),
                )
                row = cursor.fetchone()
                db_hash = row[0] if row else None

                # If hash changed, clear geometry_hash to mark as dirty
                if db_hash != new_hash:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO route_geometry (route_key, direction, geometry_hash, last_precomputed_at)
                        VALUES (?, ?, NULL, CURRENT_TIMESTAMP)
                        """,
                        (rk, direction),
                    )

                # Perform the actual update
                for rs in stops:
                    route_id = rs.get("route", "")
                    bound = rs.get("bound", "O")
                    direction = 1 if str(bound).upper() in ("O", "1") else 2
                    stop_id = str(rs.get("stop") or rs.get("stop_id") or "")
                    if not stop_id:
                        continue

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO route_stops
                        (route_key, route_id, stop_id, direction, service_type, sequence, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            rk,
                            route_id,
                            stop_id,
                            direction,
                            rs.get("service_type", 1),
                            rs.get("seq", rs.get("sequence", 0)),
                        ),
                    )
                    updated_count += 1

            conn.commit()
            logger.info(f"Inserted/updated {updated_count} route-stops")
            return updated_count

    def get_routes(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            try:
                return pd.read_sql_query(
                    """
                    SELECT route_key, route_id, route_name, origin_en as origin, destination_en as destination,
                           origin_tc, destination_tc,
                           service_type, company, COALESCE(provider_route_id,'') as provider_route_id,
                           geometry_hash, last_precomputed_at
                    FROM routes ORDER BY route_key
                    """,
                    conn,
                )
            except sqlite3.OperationalError:
                return pd.read_sql_query(
                    """
                    SELECT route_id as route_key, route_id, route_name, origin_en as origin, destination_en as destination,
                           '' as origin_tc, '' as destination_tc,
                           service_type, company, NULL as geometry_hash, NULL as last_precomputed_at
                    FROM routes ORDER BY route_id
                    """,
                    conn,
                )

    def update_route_geometry_status(
        self, route_key: str, direction: int, geometry_hash: str
    ):
        """Update the precomputed geometry status for a route direction."""
        with sqlite3.connect(self.db_path) as conn:
            self._ensure_route_geometry_table(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO route_geometry (route_key, direction, geometry_hash, last_precomputed_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (route_key, direction, geometry_hash),
            )
            conn.commit()

    def get_route_geometry_hashes(self) -> dict[tuple[str, int], str]:
        """Get all precomputed geometry hashes from DB as {(route_key, direction): hash}."""
        with sqlite3.connect(self.db_path) as conn:
            self._ensure_route_geometry_table(conn)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT route_key, direction, geometry_hash FROM route_geometry"
            )
            return {(rk, d): h for rk, d, h in cursor.fetchall()}

    def mark_route_geometry_dirty(self, route_key: str, direction: int):
        """Mark a route direction as dirty by clearing its hash."""
        with sqlite3.connect(self.db_path) as conn:
            self._ensure_route_geometry_table(conn)
            conn.execute(
                "UPDATE route_geometry SET geometry_hash = NULL WHERE route_key = ? AND direction = ?",
                (route_key, direction),
            )
            conn.commit()

    def delete_route_stops_for_route_key(self, route_key: str) -> int:
        """Remove all route_stops for a route (all directions). Use before re-inserting reshaped MTR D/U rows."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM route_stops WHERE route_key = ?", (route_key,))
            n = cur.rowcount or 0
            conn.commit()
            return n

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
        self, route_key_or_id: str, direction: int = 1, service_type: int = 1
    ) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            try:
                return pd.read_sql_query(
                    """
                    SELECT rs.route_key, rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                           s.lat, s.lng, rs.sequence, s.company
                    FROM route_stops rs
                    JOIN stops s ON rs.stop_id = s.stop_id
                    WHERE (rs.route_key = ? OR rs.route_id = ?) AND rs.direction = ? AND rs.service_type = ?
                    ORDER BY rs.sequence
                    """,
                    conn,
                    params=(route_key_or_id, route_key_or_id, direction, service_type),
                )
            except sqlite3.OperationalError:
                return pd.read_sql_query(
                    """
                    SELECT rs.route_id as route_key, rs.route_id, rs.stop_id, s.stop_name_en as stop_name,
                           s.lat, s.lng, rs.sequence, s.company
                    FROM route_stops rs
                    JOIN stops s ON rs.stop_id = s.stop_id
                    WHERE rs.route_id = ? AND rs.direction = ? AND rs.service_type = ?
                    ORDER BY rs.sequence
                    """,
                    conn,
                    params=(route_key_or_id, direction, service_type),
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

    def is_transport_catalog_complete(
        self,
        min_routes: int = 500,
        min_stops: int = 500,
        min_route_stops: int = 5000,
    ) -> bool:
        """
        True if SQLite row counts look like a full transport import (not age-based).
        Used to skip redundant API work on repeat `yuutraffic --update` when enabled in conf.
        """
        stats = self.get_database_stats()
        if stats["routes_count"] < min_routes:
            return False
        if stats["route_stops_count"] < min_route_stops:
            return False
        if stats["stops_count"] < min_stops:
            return False
        if not stats.get("last_routes_update"):
            return False
        return True

    def log_update(
        self,
        update_type: str,
        records_updated: int,
        status: str,
        error_message: str | None = None,
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
