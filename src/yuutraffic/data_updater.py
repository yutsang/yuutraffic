"""
Hong Kong Bus Data Updater - KMB/LWB and Citybus (CTB)
Updates local database with routes, stops, and route-stops data from open APIs
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests

from .database_manager import KMBDatabaseManager, route_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("data_updater.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Company codes for route_key (internal lookup: company_routeNum)
KMB_PREFIX = "KMB"
CTB_PREFIX = "CTB"
HTTP_OK = 200


class KMBDataUpdater:
    """Fetches and updates KMB data from the official API"""

    def __init__(self, db_path: str = "kmb_data.db"):
        self.db_manager = KMBDatabaseManager(db_path)
        self.base_url = "https://data.etabus.gov.hk/v1/transport/kmb"
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "KMB-Dashboard/1.0", "Accept": "application/json"}
        )
        self._bulk_stops_forbidden = False

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
            logger.error(f"Error fetching KMB routes: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching KMB routes: {e}")
            return []

    def fetch_stops(self) -> list[dict[str, Any]]:
        self._bulk_stops_forbidden = False
        try:
            logger.info("Fetching KMB stops from API...")
            url = f"{self.base_url}/stop"
            response = self.session.get(url, timeout=30)
            if response.status_code == 403:
                self._bulk_stops_forbidden = True
                logger.warning(
                    "KMB bulk /stop returned 403 (common outside Hong Kong). "
                    "Stop names/coords will be filled via per-stop /stop/{id} after route-stops load."
                )
                return []
            response.raise_for_status()
            data = response.json()
            if "data" in data:
                logger.info(f"Fetched {len(data['data'])} stops")
                return data["data"]
            return []
        except requests.exceptions.HTTPError as e:
            if getattr(e.response, "status_code", None) == 403:
                self._bulk_stops_forbidden = True
                logger.warning(
                    "KMB bulk /stop forbidden; will backfill stops per ID after route-stops."
                )
            else:
                logger.error("Error fetching KMB stops: %s", e)
            return []
        except requests.exceptions.RequestException as e:
            logger.error("Error fetching KMB stops: %s", e)
            return []
        except Exception as e:
            logger.error("Unexpected error fetching KMB stops: %s", e)
            return []

    def fetch_route_stops(
        self, route_id: str, direction: str = "outbound", service_type: int = 1
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
        """KMB route-stop API expects direction 'outbound'/'inbound', not 'O'/'I'."""
        all_route_stops = []
        for i, route in enumerate(routes):
            route_id = route.get("route") or route.get("route_id")
            if not route_id:
                continue
            for direction_bound, api_dir in [("O", "outbound"), ("I", "inbound")]:
                route_stops = self.fetch_route_stops(route_id, api_dir)
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
            updated = self.db_manager.insert_routes(routes, company="KMB/LWB")
            self.db_manager.log_update("routes", updated, "success")
            return True
        except Exception as e:
            self.db_manager.log_update("routes", 0, "error", str(e))
            return False

    def update_stops(self) -> bool:
        try:
            stops = self.fetch_stops()
            if stops:
                updated = self.db_manager.insert_stops(stops, company="KMB/LWB")
                self.db_manager.log_update("stops", updated, "success")
                return True
            if self._bulk_stops_forbidden:
                self.db_manager.log_update(
                    "stops",
                    0,
                    "skipped",
                    "Bulk stops 403; backfill runs with route-stops",
                )
                return True
            self.db_manager.log_update("stops", 0, "error", "No stops data fetched")
            return False
        except Exception as e:
            self.db_manager.log_update("stops", 0, "error", str(e))
            return False

    def fetch_stop_one(self, stop_id: str) -> dict[str, Any] | None:
        """GET /stop/{id} — often works when bulk /stop list returns 403."""
        try:
            url = f"{self.base_url}/stop/{stop_id}"
            r = self.session.get(url, timeout=12)
            if r.status_code != HTTP_OK:
                return None
            block = r.json().get("data") or {}
            sid = block.get("stop") or stop_id
            if not sid:
                return None
            try:
                lat = float(block.get("lat") or 0)
                lng = float(block.get("long") or block.get("lng") or 0)
            except (TypeError, ValueError):
                lat, lng = 0.0, 0.0
            return {
                "stop": str(sid),
                "name_en": block.get("name_en") or "",
                "name_tc": block.get("name_tc") or "",
                "lat": lat,
                "long": lng,
            }
        except Exception as e:
            logger.debug("KMB stop %s: %s", stop_id, e)
            return None

    def _existing_stop_ids(self) -> set[str]:
        try:
            with sqlite3.connect(self.db_manager.db_path) as conn:
                cur = conn.execute("SELECT stop_id FROM stops")
                return {str(row[0]) for row in cur.fetchall() if row[0]}
        except sqlite3.Error:
            return set()

    def backfill_kmb_stops_from_route_stops(
        self,
        route_stops: list[dict[str, Any]],
        sleep_sec: float = 0.05,
        batch_size: int = 80,
    ) -> int:
        """Insert any stop IDs referenced by route_stops that are missing from `stops`."""
        need = {str(rs.get("stop") or "") for rs in route_stops if rs.get("stop")}
        need.discard("")
        missing = sorted(need - self._existing_stop_ids())
        if not missing:
            return 0
        logger.info(
            "Backfilling %d KMB stops via /stop/{id} (bulk list unavailable or incomplete)…",
            len(missing),
        )
        total_inserted = 0
        chunk: list[dict[str, Any]] = []
        for i, sid in enumerate(missing):
            one = self.fetch_stop_one(sid)
            if one:
                chunk.append(one)
            if len(chunk) >= batch_size or i == len(missing) - 1:
                if chunk:
                    total_inserted += self.db_manager.insert_stops(
                        chunk, company="KMB/LWB"
                    )
                    chunk = []
            time.sleep(sleep_sec)
        if total_inserted:
            logger.info("Backfilled %d KMB stop rows", total_inserted)
        return total_inserted

    def update_route_stops(self, max_routes: int | None = None) -> bool:
        try:
            routes_df = self.db_manager.get_routes()
            if routes_df.empty:
                self.db_manager.log_update(
                    "route_stops", 0, "error", "No routes in database"
                )
                return False
            # Filter to KMB routes only for this updater
            kmb_routes = routes_df[
                routes_df["company"].astype(str).str.startswith("KMB", na=False)
            ]
            if kmb_routes.empty:
                kmb_routes = routes_df
            routes = kmb_routes.to_dict("records")
            for r in routes:
                r["route"] = r.get("route_id") or r.get("route") or ""
            if max_routes:
                routes = routes[:max_routes]
            route_stops = self.fetch_all_route_stops(routes)
            if not route_stops:
                self.db_manager.log_update(
                    "route_stops", 0, "error", "No route-stops data fetched"
                )
                return False
            self.backfill_kmb_stops_from_route_stops(route_stops)
            updated = self.db_manager.insert_route_stops(
                route_stops,
                company="KMB/LWB",
                route_key_fn=lambda r: route_key("KMB", r.get("route", "")),
            )
            self.db_manager.log_update("route_stops", updated, "success")
            return True
        except Exception as e:
            self.db_manager.log_update("route_stops", 0, "error", str(e))
            return False

    def update_all_data(self, max_routes: int | None = None) -> bool:
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


class CitybusDataUpdater:
    """Fetches and updates Citybus (CTB) data from data.gov.hk v2 API"""

    def __init__(
        self,
        db_path: str,
        base_url: str = "https://rt.data.gov.hk/v2/transport/citybus",
    ):
        self.db_manager = KMBDatabaseManager(db_path)
        self.base_url = base_url
        self.company = "CTB"
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "YuuTraffic/1.0", "Accept": "application/json"}
        )

    def fetch_routes(self) -> list[dict[str, Any]]:
        """Citybus v2: GET /route/ctb returns list of routes."""
        try:
            logger.info("Fetching Citybus routes from API...")
            url = f"{self.base_url}/route/ctb"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            routes = (
                data
                if isinstance(data, list)
                else data.get("data", data.get("routes", []))
            )
            if not isinstance(routes, list):
                routes = []
            logger.info(f"Fetched {len(routes)} Citybus routes")
            return routes
        except Exception as e:
            logger.error(f"Error fetching Citybus routes: {e}")
            return []

    def fetch_stop(self, stop_id: str) -> dict[str, Any] | None:
        """Citybus v2: GET /stop/{stop_id} - no bulk endpoint, fetch per stop."""
        try:
            url = f"{self.base_url}/stop/{stop_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            d = data.get("data") if isinstance(data, dict) and "data" in data else data
            if isinstance(d, dict) and d.get("stop"):
                return d
            return None
        except Exception:
            return None

    def fetch_stops(self, stop_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Citybus v2: no bulk /stop; fetch per stop_id. If stop_ids is None, returns []."""
        if not stop_ids:
            return []
        stops = []
        for i, sid in enumerate(set(stop_ids)):
            s = self.fetch_stop(sid)
            if s:
                stops.append(s)
            if (i + 1) % 100 == 0:
                logger.info(f"Fetched {i + 1}/{len(set(stop_ids))} Citybus stops")
            time.sleep(0.05)
        return stops

    def fetch_route_stops(
        self, routes: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Citybus v2: GET /route-stop/ctb/{route}/{direction} - requires route and direction per request."""
        all_items = []
        stop_ids = set()
        for i, route in enumerate(routes):
            route_id = str(route.get("route") or route.get("route_id") or "").strip()
            if not route_id:
                continue
            for api_dir in ["outbound", "inbound"]:
                bound = "O" if api_dir == "outbound" else "I"
                try:
                    url = f"{self.base_url}/route-stop/ctb/{route_id}/{api_dir}"
                    response = self.session.get(url, timeout=15)
                    response.raise_for_status()
                    data = response.json()
                    items = data.get("data", []) if isinstance(data, dict) else []
                    for rs in items:
                        rs["route"] = route_id
                        rs["bound"] = bound
                        all_items.append(rs)
                        if rs.get("stop"):
                            stop_ids.add(str(rs["stop"]))
                except Exception as e:
                    logger.debug(f"Route-stop {route_id} {api_dir}: {e}")
                time.sleep(0.1)
            if (i + 1) % 50 == 0:
                logger.info(f"Processed {i + 1}/{len(routes)} Citybus routes")
        logger.info(
            f"Fetched {len(all_items)} Citybus route-stop entries, {len(stop_ids)} unique stops"
        )
        return all_items, stop_ids

    def _normalize_ctb_route(self, r: dict) -> dict:
        """Map Citybus API fields to our schema. CTB API uses route, orig_tc, dest_tc, etc."""
        route_id = str(
            r.get("route") or r.get("route_no") or r.get("route_id") or ""
        ).strip()
        if not route_id:
            return {}
        orig = r.get("orig_en") or r.get("origin") or r.get("origin_en") or ""
        dest = r.get("dest_en") or r.get("destination") or r.get("destination_en") or ""
        orig_tc = r.get("orig_tc") or r.get("origin_tc") or ""
        dest_tc = r.get("dest_tc") or r.get("destination_tc") or ""
        return {
            "route": route_id,
            "orig_en": orig,
            "dest_en": dest,
            "orig_tc": orig_tc,
            "dest_tc": dest_tc,
            "service_type": r.get("service_type", 1),
        }

    def _normalize_ctb_stop(self, s: dict) -> dict:
        try:
            lat = float(s.get("lat") or s.get("latitude") or 0)
            lng = float(s.get("long") or s.get("lng") or s.get("longitude") or 0)
        except (TypeError, ValueError):
            lat, lng = 0.0, 0.0
        stop_id = str(s.get("stop") or s.get("stop_id") or s.get("id") or "")
        name_en = s.get("name_en") or s.get("name") or s.get("nameEn") or ""
        name_tc = s.get("name_tc") or s.get("nameTc") or ""
        return {
            "stop": stop_id,
            "lat": lat,
            "long": lng,
            "name_en": name_en,
            "name_tc": name_tc,
        }

    def update_routes(self) -> bool:
        try:
            routes = self.fetch_routes()
            if not routes:
                self.db_manager.log_update(
                    "routes_ctb", 0, "error", "No Citybus routes fetched"
                )
                return False
            normalized = []
            for r in routes:
                n = self._normalize_ctb_route(r)
                if n and n.get("route"):
                    normalized.append(n)
            updated = self.db_manager.insert_routes(normalized, company=self.company)
            self.db_manager.log_update("routes_ctb", updated, "success")
            return True
        except Exception as e:
            self.db_manager.log_update("routes_ctb", 0, "error", str(e))
            return False

    def update_stops(self, stop_ids: list[str] | None = None) -> bool:
        """Citybus: fetch stops by ID (no bulk API). Stops are populated during update_route_stops."""
        if not stop_ids:
            self.db_manager.log_update(
                "stops_ctb", 0, "skipped", "Run route-stops first to populate stops"
            )
            return True
        try:
            stops = self.fetch_stops(stop_ids)
            if not stops:
                return True
            normalized = [
                self._normalize_ctb_stop(s)
                for s in stops
                if self._normalize_ctb_stop(s).get("stop")
            ]
            updated = self.db_manager.insert_stops(normalized, company=self.company)
            self.db_manager.log_update("stops_ctb", updated, "success")
            return True
        except Exception as e:
            self.db_manager.log_update("stops_ctb", 0, "error", str(e))
            return False

    def update_route_stops(self) -> bool:
        try:
            routes_df = self.db_manager.get_routes()
            ctb_routes = routes_df[routes_df["company"] == self.company]
            if ctb_routes.empty:
                self.db_manager.log_update(
                    "route_stops_ctb", 0, "skipped", "No CTB routes"
                )
                return True
            routes = ctb_routes.to_dict("records")
            for r in routes:
                r["route"] = r.get("route_id", r.get("route", ""))

            items, stop_ids = self.fetch_route_stops(routes)
            if not items:
                self.db_manager.log_update(
                    "route_stops_ctb", 0, "error", "No Citybus route-stops fetched"
                )
                return False

            if stop_ids:
                logger.info(f"Fetching {len(stop_ids)} Citybus stop details...")
                stops = self.fetch_stops(list(stop_ids))
                if stops:
                    norm = [
                        self._normalize_ctb_stop(s)
                        for s in stops
                        if self._normalize_ctb_stop(s).get("stop")
                    ]
                    self.db_manager.insert_stops(norm, company=self.company)

            converted = []
            for rs in items:
                route_id = str(rs.get("route") or "")
                if not route_id:
                    continue
                bound = rs.get("bound", rs.get("dir", "O"))
                if isinstance(bound, int):
                    bound = "O" if bound == 1 else "I"
                converted.append(
                    {
                        "route": route_id,
                        "stop": str(rs.get("stop") or rs.get("stop_id") or ""),
                        "bound": bound,
                        "seq": int(rs.get("seq") or rs.get("sequence") or 0),
                        "service_type": rs.get("service_type", 1),
                    }
                )
            updated = self.db_manager.insert_route_stops(
                converted,
                company=self.company,
                route_key_fn=lambda r: route_key(self.company, r.get("route", "")),
            )
            self.db_manager.log_update("route_stops_ctb", updated, "success")
            return True
        except Exception as e:
            self.db_manager.log_update("route_stops_ctb", 0, "error", str(e))
            return False

    def update_all_data(self) -> bool:
        success = True
        if not self.update_routes():
            success = False
        if not self.update_route_stops():
            success = False
        if not self.update_stops():
            success = False
        return success


GMB_REGIONS = ("HKI", "KLN", "NT")

# Candidate MTR Bus / feeder route names — invalid names return empty busStop and are skipped.
MTR_BUS_ROUTE_CANDIDATES = frozenset(
    {
        "K12",
        "K14",
        "K17",
        "K18",
        "K40",
        "K41",
        "K45",
        "K45A",
        "K48",
        "K50",
        "K51",
        "K52",
        "K53",
        "K54",
        "K58",
        "K63A",
        "K63B",
        "K64P",
        "K64S",
        "K65",
        "K66",
        "K66A",
        "K66S",
        "K67",
        "K68",
        "K71",
        "K72",
        "K73",
        "K74",
        "K75",
        "K76",
        "506",
        "506A",
        "507",
        "507P",
        "610",
        "614",
        "614P",
        "615",
        "615P",
        "705",
        "706",
        "720",
        "720M",
        "751",
        "751P",
        "A30",
        "A31",
        "A32",
        "A33",
        "A33X",
        "A34",
        "A36",
        "A37",
        "A38",
        "A41",
        "A41P",
        "A42",
        "A43",
        "A43P",
        "A46",
        "A47X",
    }
)


class GMBDataUpdater:
    """Green minibus (專線小巴) from Transport Department data.etagmb.gov.hk API."""

    def __init__(self, db_path: str, base_url: str = "https://data.etagmb.gov.hk"):
        self.db_manager = KMBDatabaseManager(db_path)
        self.base_url = base_url.rstrip("/")
        self.company = "GMB"
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "YuuTraffic/1.0", "Accept": "application/json"}
        )

    def _get(self, path: str) -> dict[str, Any]:
        r = self.session.get(f"{self.base_url}{path}", timeout=25)
        r.raise_for_status()
        return r.json()

    def _route_codes(self, region: str) -> list[str]:
        try:
            data = self._get(f"/route/{region}")
            routes = (data.get("data") or {}).get("routes") or []
            return [str(x) for x in routes]
        except Exception as e:
            logger.warning("GMB route list %s: %s", region, e)
            return []

    def _route_detail(self, region: str, route_code: str) -> dict[str, Any] | None:
        try:
            data = self._get(f"/route/{region}/{route_code}")
            block = data.get("data")
            if isinstance(block, list) and block:
                return block[0]
            if isinstance(block, dict):
                return block
        except Exception as e:
            logger.debug("GMB route %s/%s: %s", region, route_code, e)
        return None

    def _route_stops(self, route_id_num: int, route_seq: int) -> list[dict[str, Any]]:
        try:
            data = self._get(f"/route-stop/{route_id_num}/{route_seq}")
            rs = (data.get("data") or {}).get("route_stops") or []
            return rs if isinstance(rs, list) else []
        except Exception as e:
            logger.debug("GMB route-stop %s/%s: %s", route_id_num, route_seq, e)
            return []

    def _stop_coords(self, stop_id_num: int) -> tuple[float, float] | None:
        try:
            data = self._get(f"/stop/{stop_id_num}")
            wgs = ((data.get("data") or {}).get("coordinates") or {}).get("wgs84") or {}
            lat = float(wgs.get("latitude", 0))
            lng = float(wgs.get("longitude", 0))
            if lat and lng:
                return lat, lng
        except Exception as e:
            logger.debug("GMB stop %s: %s", stop_id_num, e)
        return None

    def update_all(self, sleep_sec: float = 0.06) -> bool:
        """Fetch all GMB routes, stops, and route–stop links (many HTTP calls)."""
        all_route_rows: list[dict[str, Any]] = []
        all_rs: list[dict[str, Any]] = []
        stop_meta: dict[str, dict[str, Any]] = {}

        for region in GMB_REGIONS:
            codes = self._route_codes(region)
            logger.info("GMB %s: %d route codes", region, len(codes))
            for i, code in enumerate(codes):
                detail = self._route_detail(region, code)
                time.sleep(sleep_sec)
                if not detail:
                    continue
                rid_num = int(detail.get("route_id", 0))
                if not rid_num:
                    continue
                directions = detail.get("directions") or []
                if not directions:
                    continue
                d0 = directions[0]
                display_id = f"{region}-{code}"
                all_route_rows.append(
                    {
                        "route": display_id,
                        "orig_en": d0.get("orig_en") or "",
                        "dest_en": d0.get("dest_en") or "",
                        "orig_tc": d0.get("orig_tc") or "",
                        "dest_tc": d0.get("dest_tc") or "",
                        "service_type": 1,
                        "provider_route_id": str(rid_num),
                    }
                )
                for d in directions:
                    rseq = int(d.get("route_seq", 0))
                    if not rseq:
                        continue
                    stops = self._route_stops(rid_num, rseq)
                    time.sleep(sleep_sec)
                    bound = "O" if rseq == 1 else "I"
                    for row in stops:
                        sid_num = int(row.get("stop_id", 0))
                        sseq = int(row.get("stop_seq", 0))
                        if not sid_num or not sseq:
                            continue
                        sid = f"GMB_{sid_num}"
                        all_rs.append(
                            {
                                "route": display_id,
                                "stop": sid,
                                "bound": bound,
                                "seq": sseq,
                                "service_type": 1,
                            }
                        )
                        if sid not in stop_meta:
                            stop_meta[sid] = {
                                "stop": sid,
                                "name_en": row.get("name_en") or "",
                                "name_tc": row.get("name_tc") or "",
                                "lat": 0.0,
                                "long": 0.0,
                            }
                if (i + 1) % 40 == 0:
                    logger.info(
                        "GMB %s: processed %d/%d routes", region, i + 1, len(codes)
                    )

        if not all_route_rows:
            self.db_manager.log_update("routes_gmb", 0, "error", "No GMB routes")
            return False

        self.db_manager.insert_routes(all_route_rows, company=self.company)

        for sid, meta in stop_meta.items():
            nums = sid.replace("GMB_", "", 1)
            try:
                coords = self._stop_coords(int(nums))
                time.sleep(sleep_sec)
            except ValueError:
                coords = None
            if coords:
                meta["lat"], meta["long"] = coords

        stops_list = list(stop_meta.values())
        self.db_manager.insert_stops(stops_list, company=self.company)

        self.db_manager.insert_route_stops(
            all_rs,
            company=self.company,
            route_key_fn=lambda r: route_key(self.company, r.get("route", "")),
        )
        self.db_manager.log_update("routes_gmb", len(all_route_rows), "success")
        return True


class MTRBusDataUpdater:
    """MTR Bus & feeder routes via rt.data.gov.hk POST getSchedule (stops + schematic map coords)."""

    def __init__(self, db_path: str, schedule_url: str | None = None):
        self.db_manager = KMBDatabaseManager(db_path)
        self.company = "MTR Bus"
        self.schedule_url = (
            schedule_url or "https://rt.data.gov.hk/v1/transport/mtr/bus/getSchedule"
        )
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "YuuTraffic/1.0", "Accept": "application/json"}
        )

    def _fetch_schedule(self, route_name: str, lang: str = "en") -> dict[str, Any]:
        r = self.session.post(
            self.schedule_url,
            json={"language": lang, "routeName": route_name},
            timeout=25,
        )
        r.raise_for_status()
        return r.json()

    def update_all(self, sleep_sec: float = 0.15) -> bool:
        from .mtr_bus_geo import enrich_mtr_stop_row, mtr_bus_stop_leg, mtr_stop_labels

        routes_out: list[dict[str, Any]] = []
        all_rs: list[dict[str, Any]] = []
        stops_acc: list[dict[str, Any]] = []

        for name in sorted(MTR_BUS_ROUTE_CANDIDATES):
            try:
                en = self._fetch_schedule(name, "en")
                time.sleep(sleep_sec)
            except Exception as e:
                logger.debug("MTR Bus %s: %s", name, e)
                continue

            stops_en = en.get("busStop") or []
            if not isinstance(stops_en, list) or not stops_en:
                continue

            down: list[dict[str, Any]] = []
            up: list[dict[str, Any]] = []
            for bs in stops_en:
                if not isinstance(bs, dict):
                    continue
                sid = str(bs.get("busStopId") or "")
                leg = mtr_bus_stop_leg(sid)
                if leg == "U":
                    up.append(bs)
                else:
                    down.append(bs)

            if not up:
                # No -U- stop ids: treat whole list as one direction (legacy API shape).
                down = [bs for bs in stops_en if isinstance(bs, dict)]
                up = []

            if down:
                first_id = str(down[0].get("busStopId", ""))
                last_id = str(down[-1].get("busStopId", ""))
            elif up:
                first_id = str(up[0].get("busStopId", ""))
                last_id = str(up[-1].get("busStopId", ""))
            else:
                continue
            if not first_id or not last_id:
                continue

            o_e, o_t = mtr_stop_labels(first_id)
            d_e, d_t = mtr_stop_labels(last_id)
            routes_out.append(
                {
                    "route": name,
                    "orig_en": o_e,
                    "dest_en": d_e,
                    "orig_tc": o_t,
                    "dest_tc": d_t,
                    "service_type": 1,
                    "provider_route_id": name,
                }
            )

            def _emit_leg(
                leg_stops: list[dict[str, Any]], bound: str, leg: str | None
            ) -> None:
                nleg = len(leg_stops)
                for idx, bs in enumerate(leg_stops):
                    sid = str(bs.get("busStopId") or "")
                    if not sid:
                        continue
                    seq = idx + 1
                    en_l, tc_l, lat, lng = enrich_mtr_stop_row(
                        name, sid, seq, nleg, leg
                    )
                    stops_acc.append(
                        {
                            "stop": sid,
                            "name_en": en_l,
                            "name_tc": tc_l,
                            "lat": lat,
                            "long": lng,
                        }
                    )
                    all_rs.append(
                        {
                            "route": name,
                            "stop": sid,
                            "bound": bound,
                            "seq": seq,
                            "service_type": 1,
                        }
                    )

            if not down and up:
                _emit_leg(up, "O", "U")
            else:
                if down:
                    _emit_leg(down, "O", "D" if up else None)
                if up:
                    _emit_leg(up, "I", "U")

        if not routes_out:
            self.db_manager.log_update(
                "routes_mtrb", 0, "error", "No MTR Bus routes matched candidates"
            )
            return False

        for r in routes_out:
            rk = route_key(self.company, r.get("route", ""))
            self.db_manager.delete_route_stops_for_route_key(rk)

        self.db_manager.insert_routes(routes_out, company=self.company)
        self.db_manager.insert_stops(
            stops_acc, company=self.company, require_hk_bounds=False
        )
        self.db_manager.insert_route_stops(
            all_rs,
            company=self.company,
            route_key_fn=lambda r: route_key(self.company, r.get("route", "")),
        )
        self.db_manager.log_update("routes_mtrb", len(routes_out), "success")
        logger.info("MTR Bus: stored %d routes", len(routes_out))
        return True


def load_red_minibus_routes(project_root: Path) -> list[dict[str, Any]]:
    """Curated red minibus corridors (no government open-data ETA)."""
    p = project_root / "data" / "01_raw" / "red_minibus_routes.json"
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("red_minibus_routes.json: %s", e)
        return []


def update_red_minibus(db_path: str, project_root: Path | None = None) -> bool:
    root = project_root or Path(__file__).resolve().parent.parent.parent
    rows = load_red_minibus_routes(root)
    if not rows:
        logger.info(
            "No red minibus JSON entries (optional file data/01_raw/red_minibus_routes.json)"
        )
        return True
    db = KMBDatabaseManager(db_path)
    norm = []
    for r in rows:
        rid = str(r.get("route_id") or r.get("route") or "").strip()
        if not rid:
            continue
        norm.append(
            {
                "route": rid,
                "orig_en": r.get("origin_en", "") or "",
                "dest_en": r.get("destination_en", "") or "",
                "orig_tc": r.get("origin_tc", "") or "",
                "dest_tc": r.get("destination_tc", "") or "",
                "service_type": 1,
            }
        )
    if not norm:
        return True
    db.insert_routes(norm, company="RMB")
    db.log_update("routes_rmb", len(norm), "success")
    return True


def run_full_transport_update(
    db_path: str,
    *,
    max_routes: int | None = None,
    kmb_only: bool = False,
    ctb_only: bool = False,
    ctb_base: str = "https://rt.data.gov.hk/v2/transport/citybus",
    gmb_base: str = "https://data.etagmb.gov.hk",
    mtr_url: str | None = None,
    project_root: Path | None = None,
) -> None:
    """KMB + Citybus + GMB + MTR Bus + red minibus (GMB is slow)."""
    root = project_root or Path(__file__).resolve().parent.parent.parent
    run_kmb = not ctb_only
    run_ctb = not kmb_only
    if run_kmb:
        KMBDataUpdater(db_path).update_all_data(max_routes)
    if run_ctb:
        CitybusDataUpdater(db_path, ctb_base).update_all_data()
    if not kmb_only and not ctb_only:
        logging.info("Green minibus (GMB) — this may take several minutes...")
        GMBDataUpdater(db_path, gmb_base).update_all()
        MTRBusDataUpdater(db_path, mtr_url).update_all()
        update_red_minibus(db_path, root)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Low-level transport DB updater. Prefer: yuutraffic --update "
            "(KMB, Citybus, GMB, MTR Bus, red minibus + incremental map geometry)."
        )
    )
    parser.add_argument("--routes", action="store_true", help="KMB/CTB routes only")
    parser.add_argument("--stops", action="store_true", help="KMB/CTB stops only")
    parser.add_argument(
        "--route-stops", action="store_true", help="KMB/CTB route-stops only"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Same as default full refresh (kept for scripts; optional)",
    )
    parser.add_argument(
        "--kmb-only",
        action="store_true",
        help="With full refresh: KMB only (skip CTB/GMB/MTR/RMB)",
    )
    parser.add_argument(
        "--ctb-only",
        action="store_true",
        help="With full refresh: Citybus only (skip KMB/GMB/MTR/RMB)",
    )
    parser.add_argument(
        "--gmb-only", action="store_true", help="Green minibus (etagmb) only — long run"
    )
    parser.add_argument(
        "--mtr-only", action="store_true", help="MTR Bus / feeder routes only"
    )
    parser.add_argument(
        "--rmb-only", action="store_true", help="Red minibus curated JSON only"
    )
    parser.add_argument("--max-routes", type=int)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--db-path", default="data/01_raw/kmb_data.db")
    args = parser.parse_args()

    db_path = args.db_path
    run_kmb = (
        not args.ctb_only
        and not args.gmb_only
        and not args.mtr_only
        and not args.rmb_only
    )
    run_ctb = (
        not args.kmb_only
        and not args.gmb_only
        and not args.mtr_only
        and not args.rmb_only
    )

    from .config import load_config

    config = load_config()
    ctb_base = config.get("api", {}).get(
        "citybus_base_url", "https://rt.data.gov.hk/v2/transport/citybus"
    )
    gmb_base = config.get("api", {}).get("gmb_base_url", "https://data.etagmb.gov.hk")
    mtr_url = config.get("api", {}).get("mtr_bus_schedule_url")
    project_root = Path(__file__).resolve().parent.parent.parent

    if args.gmb_only:
        GMBDataUpdater(db_path, gmb_base).update_all()
        return
    if args.mtr_only:
        MTRBusDataUpdater(db_path, mtr_url).update_all()
        return
    if args.rmb_only:
        update_red_minibus(db_path, project_root)
        return

    if args.status:
        db = KMBDatabaseManager(db_path)
        stats = db.get_database_stats()
        for k, v in stats.items():
            logging.info(f"  {k}: {v}")
        return

    if args.routes:
        if run_kmb:
            KMBDataUpdater(db_path).update_routes()
        if run_ctb:
            CitybusDataUpdater(db_path, ctb_base).update_routes()
        return
    if args.stops:
        if run_kmb:
            KMBDataUpdater(db_path).update_stops()
        if run_ctb:
            CitybusDataUpdater(db_path, ctb_base).update_stops()
        return
    if args.route_stops:
        if run_kmb:
            KMBDataUpdater(db_path).update_route_stops(args.max_routes)
        if run_ctb:
            CitybusDataUpdater(db_path, ctb_base).update_route_stops()
        return

    # Default, or --all: one-shot full data refresh (precompute is a separate command)
    logging.info(
        "Full transport data update (KMB + Citybus + GMB + MTR Bus + red minibus)"
    )
    run_full_transport_update(
        db_path,
        max_routes=args.max_routes,
        kmb_only=args.kmb_only,
        ctb_only=args.ctb_only,
        ctb_base=ctb_base,
        gmb_base=gmb_base,
        mtr_url=mtr_url,
        project_root=project_root,
    )


if __name__ == "__main__":
    main()
