"""
Compare lightweight live API snapshots to the SQLite catalog so `yuutraffic --update`
can skip a full download when nothing changed (no wall-clock age).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:48]


def _kmb_effective_lines_from_api(routes: list[dict[str, Any]]) -> list[str]:
    """Match KMB insert_routes: one row per route number; last API row wins (same as INSERT OR REPLACE)."""
    last_by_route: dict[str, tuple[str, int]] = {}
    for r in routes:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("route") or r.get("route_id") or "").strip()
        if not rid:
            continue
        st = int(str(r.get("service_type", 1) or 1))
        last_by_route[rid] = (rid, st)
    return sorted(f"{a}:{b}" for a, b in last_by_route.values())


def _ctb_lines_from_api(routes: list[dict[str, Any]]) -> list[str]:
    lines = []
    for r in routes:
        if not isinstance(r, dict):
            continue
        rid = str(
            r.get("route") or r.get("route_no") or r.get("route_id") or ""
        ).strip()
        if not rid:
            continue
        orig = str(r.get("orig_en") or r.get("origin_en") or r.get("origin") or "")
        dest = str(
            r.get("dest_en") or r.get("destination_en") or r.get("destination") or ""
        )
        lines.append(f"{rid}|{orig}|{dest}")
    lines.sort()
    return lines


def fetch_kmb_route_fingerprint(session: requests.Session, base_url: str) -> str | None:
    try:
        url = f"{base_url.rstrip('/')}/route"
        r = session.get(url, timeout=35)
        r.raise_for_status()
        data = r.json()
        routes = data.get("data", []) if isinstance(data, dict) else []
        if not isinstance(routes, list):
            return None
        return _sha("\n".join(_kmb_effective_lines_from_api(routes)))
    except Exception as e:
        logger.debug("KMB live fingerprint: %s", e)
        return None


def fetch_ctb_route_fingerprint(session: requests.Session, base_url: str) -> str | None:
    try:
        url = f"{base_url.rstrip('/')}/route/ctb"
        r = session.get(url, timeout=35)
        r.raise_for_status()
        data = r.json()
        routes = (
            data if isinstance(data, list) else data.get("data", data.get("routes", []))
        )
        if not isinstance(routes, list):
            return None
        return _sha("\n".join(_ctb_lines_from_api(routes)))
    except Exception as e:
        logger.debug("CTB live fingerprint: %s", e)
        return None


def fetch_gmb_route_fingerprint(session: requests.Session, base_url: str) -> str | None:
    try:
        lines: list[str] = []
        base = base_url.rstrip("/")
        for region in ("HKI", "KLN", "NT"):
            r = session.get(f"{base}/route/{region}", timeout=25)
            r.raise_for_status()
            data = r.json()
            codes = (data.get("data") or {}).get("routes") or []
            if not isinstance(codes, list):
                continue
            for code in codes:
                lines.append(f"{region}-{code}")
        lines.sort()
        return _sha("\n".join(lines))
    except Exception as e:
        logger.debug("GMB live fingerprint: %s", e)
        return None


def _mtr_schedule_stop_sequence(payload: dict[str, Any]) -> str:
    bus = payload.get("busStop") or []
    if not isinstance(bus, list):
        return ""
    return "|".join(str(x.get("busStopId") or "") for x in bus if isinstance(x, dict))


def _fetch_one_mtr_schedule(
    session: requests.Session, mtr_url: str, route_name: str
) -> tuple[str, str]:
    try:
        r = session.post(
            mtr_url,
            json={"language": "en", "routeName": route_name},
            timeout=15,
        )
        r.raise_for_status()
        j = r.json()
        return route_name, _mtr_schedule_stop_sequence(j)
    except Exception:
        return route_name, "__ERR__"


def fetch_mtr_route_fingerprint(
    mtr_url: str, route_names: frozenset[str], max_workers: int = 10
) -> str | None:
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "YuuTraffic/1.0", "Accept": "application/json"}
    )
    names = sorted(route_names)
    rows: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_fetch_one_mtr_schedule, session, mtr_url, n) for n in names]
        for fu in as_completed(futs):
            rows.append(fu.result())
    if any(s == "__ERR__" for _, s in rows):
        return None
    rows.sort(key=lambda x: x[0])
    return _sha("\n".join(f"{n}:{s}" for n, s in rows))


def red_minibus_canonical_fingerprint(project_root: Path) -> str:
    p = project_root / "data" / "01_raw" / "red_minibus_routes.json"
    if not p.is_file():
        return _sha("")
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _sha("")
    if not isinstance(data, list):
        return _sha("")
    ids = sorted(
        str(r.get("route_id") or r.get("route") or "").strip()
        for r in data
        if isinstance(r, dict)
    )
    ids = [x for x in ids if x]
    return _sha("\n".join(ids))


def db_kmb_fingerprint(conn: sqlite3.Connection) -> str | None:
    try:
        cur = conn.execute("""
            SELECT route_id, service_type FROM routes
            WHERE company LIKE 'KMB%'
            ORDER BY route_id, service_type
            """)
        lines = [f"{str(r[0]).strip()}:{int(r[1] or 1)}" for r in cur.fetchall()]
        return _sha("\n".join(lines))
    except sqlite3.Error as e:
        logger.debug("DB KMB fingerprint: %s", e)
        return None


def db_ctb_fingerprint(conn: sqlite3.Connection) -> str | None:
    try:
        cur = conn.execute("""
            SELECT route_id, COALESCE(origin_en,''), COALESCE(destination_en,'')
            FROM routes WHERE company = 'CTB'
            ORDER BY route_id, origin_en, destination_en
            """)
        lines = [f"{str(r[0]).strip()}|{r[1]}|{r[2]}" for r in cur.fetchall()]
        return _sha("\n".join(lines))
    except sqlite3.Error as e:
        logger.debug("DB CTB fingerprint: %s", e)
        return None


def db_gmb_fingerprint(conn: sqlite3.Connection) -> str | None:
    try:
        cur = conn.execute(
            "SELECT route_id FROM routes WHERE company = 'GMB' ORDER BY route_id"
        )
        lines = [str(r[0]).strip() for r in cur.fetchall() if r[0]]
        return _sha("\n".join(lines))
    except sqlite3.Error as e:
        logger.debug("DB GMB fingerprint: %s", e)
        return None


def db_mtr_fingerprint(
    conn: sqlite3.Connection, route_names: frozenset[str]
) -> str | None:
    try:
        from .database_manager import route_key

        company = "MTR Bus"
        parts: list[str] = []
        for name in sorted(route_names):
            rk = route_key(company, name)
            cur = conn.execute(
                """
                SELECT stop_id FROM route_stops
                WHERE route_key = ? AND direction = 1
                ORDER BY sequence
                """,
                (rk,),
            )
            d_ids = [str(r[0]) for r in cur.fetchall()]
            cur = conn.execute(
                """
                SELECT stop_id FROM route_stops
                WHERE route_key = ? AND direction = 2
                ORDER BY sequence
                """,
                (rk,),
            )
            u_ids = [str(r[0]) for r in cur.fetchall()]
            seq = "|".join(d_ids + u_ids)
            parts.append(f"{name}:{seq}")
        return _sha("\n".join(parts))
    except sqlite3.Error as e:
        logger.debug("DB MTR fingerprint: %s", e)
        return None


def db_rmb_fingerprint(conn: sqlite3.Connection) -> str | None:
    try:
        cur = conn.execute(
            "SELECT route_id FROM routes WHERE company = 'RMB' ORDER BY route_id"
        )
        lines = [str(r[0]).strip() for r in cur.fetchall() if r[0]]
        return _sha("\n".join(lines))
    except sqlite3.Error as e:
        logger.debug("DB RMB fingerprint: %s", e)
        return None


def catalog_live_matches_database(
    db_path: str,
    params: dict[str, Any],
    project_root: Path,
    *,
    compare_mtr: bool = True,
) -> bool | None:
    """
    Return True if live API fingerprints match the DB (and red minibus JSON vs RMB rows).
    Return False if any source differs.
    Return None if a live fetch failed (caller should run a full refresh to be safe).
    """
    from .data_updater import MTR_BUS_ROUTE_CANDIDATES

    api = params.get("api", {}) or {}
    kmb_base = api.get("kmb_base_url", "https://data.etabus.gov.hk/v1/transport/kmb")
    ctb_base = api.get(
        "citybus_base_url", "https://rt.data.gov.hk/v2/transport/citybus"
    )
    gmb_base = api.get("gmb_base_url", "https://data.etagmb.gov.hk")
    mtr_url = api.get(
        "mtr_bus_schedule_url",
        "https://rt.data.gov.hk/v1/transport/mtr/bus/getSchedule",
    )

    session = requests.Session()
    session.headers.update(
        {"User-Agent": "YuuTraffic/1.0", "Accept": "application/json"}
    )

    live_kmb = fetch_kmb_route_fingerprint(session, kmb_base)
    live_ctb = fetch_ctb_route_fingerprint(session, ctb_base)
    live_gmb = fetch_gmb_route_fingerprint(session, gmb_base)
    live_mtr = (
        fetch_mtr_route_fingerprint(mtr_url, MTR_BUS_ROUTE_CANDIDATES)
        if compare_mtr
        else None
    )
    live_rmb = red_minibus_canonical_fingerprint(project_root)

    if live_kmb is None or live_ctb is None or live_gmb is None:
        return None
    if compare_mtr and live_mtr is None:
        return None

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return None
    try:
        db_kmb = db_kmb_fingerprint(conn)
        db_ctb = db_ctb_fingerprint(conn)
        db_gmb = db_gmb_fingerprint(conn)
        db_mtr = (
            db_mtr_fingerprint(conn, MTR_BUS_ROUTE_CANDIDATES) if compare_mtr else None
        )
        db_rmb = db_rmb_fingerprint(conn)
    finally:
        conn.close()

    if None in (db_kmb, db_ctb, db_gmb, db_rmb):
        return None
    if compare_mtr and db_mtr is None:
        return None

    if live_kmb != db_kmb:
        logger.info("Catalog diff: KMB route list changed (live vs DB).")
        return False
    if live_ctb != db_ctb:
        logger.info("Catalog diff: Citybus route list changed (live vs DB).")
        return False
    if live_gmb != db_gmb:
        logger.info("Catalog diff: GMB route list changed (live vs DB).")
        return False
    if compare_mtr and live_mtr != db_mtr:
        logger.info("Catalog diff: MTR Bus schedules / stop sets changed (live vs DB).")
        return False
    if live_rmb != db_rmb:
        logger.info("Catalog diff: red minibus routes (JSON vs DB) changed.")
        return False

    return True
