"""`yuutraffic --update` — skips heavy work when DB row counts are OK and live route APIs match the DB; see conf."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _mark_first_run_complete(project_root: str) -> None:
    d = os.path.join(project_root, "data")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".first_run_complete"), "w", encoding="utf-8") as f:
        f.write("First run completed\n")


def run_update(project_root: str | None = None) -> int:
    """
    Refresh transport data (unless minimum counts + live vs DB fingerprint match per conf) + precompute when not skipped.
    Returns 0 on success, 1 on fatal error.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = project_root or os.getcwd()
    os.chdir(root)

    from .config import load_config
    from .data_updater import run_full_transport_update
    from .database_manager import KMBDatabaseManager

    params = load_config()
    db_path = params["database"]["path"]
    if not os.path.isabs(db_path):
        db_path = os.path.join(root, db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info("📦 Initialising database schema (if new)…")
    db = KMBDatabaseManager(db_path)

    du = params.get("data_update", {}) or {}
    if (
        "skip_transport_api_if_catalog_complete" in du
        and du["skip_transport_api_if_catalog_complete"] is not None
    ):
        skip_when_complete = bool(du["skip_transport_api_if_catalog_complete"])
    else:
        legacy_h = du.get("skip_api_if_fresh_hours")
        skip_when_complete = int(legacy_h) > 0 if legacy_h is not None else True

    min_r = int(du.get("catalog_min_routes", 500) or 500)
    min_s = int(du.get("catalog_min_stops", 500) or 500)
    min_rs = int(du.get("catalog_min_route_stops", 5000) or 5000)
    compare_mtr = bool(du.get("catalog_compare_mtr", True))

    api_fresh = False
    if skip_when_complete and db.is_transport_catalog_complete(
        min_routes=min_r, min_stops=min_s, min_route_stops=min_rs
    ):
        from .catalog_fingerprint import catalog_live_matches_database

        match = catalog_live_matches_database(
            db_path, params, Path(root), compare_mtr=compare_mtr
        )
        if match is True:
            api_fresh = True
        elif match is False:
            logger.info(
                "Live APIs differ from database — running full transport refresh."
            )
        else:
            logger.warning(
                "Could not verify catalog against live APIs — running full transport refresh."
            )

    api = params.get("api", {})
    ctb_base = api.get(
        "citybus_base_url", "https://rt.data.gov.hk/v2/transport/citybus"
    )
    gmb_base = api.get("gmb_base_url", "https://data.etagmb.gov.hk")
    mtr_url = api.get("mtr_bus_schedule_url")

    if api_fresh:
        st = db.get_database_stats()
        logger.info(
            "✓ Catalog matches live APIs (%d routes, %d stops, %d route–stops in DB). "
            "Skipping download & map geometry. For a full refresh every time, set "
            "data_update.skip_transport_api_if_catalog_complete: false in conf.",
            st["routes_count"],
            st["stops_count"],
            st["route_stops_count"],
        )
    else:
        logger.info(
            "🔄 Full transport refresh: KMB, Citybus, green minibus (GMB), MTR Bus, red minibus…"
        )
        try:
            run_full_transport_update(
                db_path,
                max_routes=None,
                kmb_only=False,
                ctb_only=False,
                ctb_base=ctb_base,
                gmb_base=gmb_base,
                mtr_url=mtr_url,
                project_root=Path(root),
            )
        except Exception as e:
            logger.exception("Transport data update failed: %s", e)
            return 1
        logger.info("✅ Transport API data written to database.")

    _mark_first_run_complete(root)

    if not api_fresh:
        logger.info("🗺️  Map geometry (incremental; only new/changed routes)…")
        try:
            from .precompute import run_precompute

            run_precompute()
        except Exception as e:
            logger.warning("Map geometry step had issues: %s", e)

    logger.info("Done. Start the app with: yuutraffic")
    return 0
