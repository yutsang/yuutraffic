import os
import sqlite3
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from yuutraffic.journey import load_route_segments, nearest_clusters


def _make_trip_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE routes (
                route_key TEXT,
                route_id TEXT,
                company TEXT,
                destination_en TEXT,
                destination_tc TEXT
            );
            CREATE TABLE route_stops (
                route_key TEXT,
                route_id TEXT,
                direction INTEGER,
                sequence INTEGER,
                stop_id TEXT
            );
            CREATE TABLE stops (
                stop_id TEXT,
                stop_name_en TEXT,
                stop_name_tc TEXT,
                company TEXT,
                lat REAL,
                lng REAL
            );
            """)


def test_load_route_segments_rotates_circular_terminus(tmp_path):
    db_path = str(tmp_path / "trip.db")
    _make_trip_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO routes VALUES (?, ?, ?, ?, ?)",
            ("24", "24", "KMB", "Central Circular", "中環循環線"),
        )
        conn.executemany(
            "INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("A", "Alpha", "", "KMB", 22.30001, 114.10001),
                ("B", "Bravo", "", "KMB", 22.30002, 114.10002),
                ("C", "Central Bus Terminus", "中環總站", "KMB", 22.30003, 114.10003),
            ],
        )
        conn.executemany(
            "INSERT INTO route_stops VALUES (?, ?, ?, ?, ?)",
            [
                ("24", "24", 1, 1, "A"),
                ("24", "24", 1, 2, "B"),
                ("24", "24", 1, 3, "C"),
            ],
        )
        conn.commit()

    segments = load_route_segments(db_path)
    assert segments[0]["stops"] == ["C", "A", "B"]


def test_nearest_clusters_uses_nearest_stop(tmp_path):
    db_path = str(tmp_path / "trip.db")
    _make_trip_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("A", "Cluster A", "", "KMB", 22.30001, 114.10001),
                ("B", "Cluster A", "", "KMB", 22.30004, 114.10004),
                ("C", "Far Away", "", "KMB", 22.31000, 114.11000),
            ],
        )
        conn.commit()

    matches = nearest_clusters(
        db_path,
        22.30001,
        114.10001,
        k=1,
    )
    assert matches
    assert matches[0][0][:2] == ["A", "B"]
    assert matches[0][2] < 0.005
