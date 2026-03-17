#!/usr/bin/env python3
"""
YuuTraffic Launcher - Starts the Streamlit app with pre-flight checks.
"""

import glob
import logging
import os
import shutil
import socket
import subprocess
import sys

from .config import load_config
from .data_updater import KMBDataUpdater
from .database_manager import KMBDatabaseManager
from .web import should_update_data

logging.basicConfig(level=logging.INFO, format="%(message)s")


def _project_root():
    """Project root: src/yuutraffic/launcher.py -> go up 2 levels to project root."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def clear_cache():
    logging.info("🧹 Clearing cache and temporary files...")
    project_root = _project_root()
    os.chdir(project_root)
    for pattern in [".streamlit", "__pycache__"]:
        path = os.path.join(project_root, pattern)
        if os.path.exists(path):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                logging.info(f"   ✅ Removed {pattern}")
            except OSError:
                pass
    for f in glob.glob(os.path.join(project_root, "**/*.pyc"), recursive=True):
        try:
            os.remove(f)
        except OSError:
            pass


def main():
    project_root = _project_root()
    os.chdir(project_root)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    if os.path.join(project_root, "src") not in sys.path:
        sys.path.insert(0, os.path.join(project_root, "src"))

    params = load_config()
    logging.info("🚌 YuuTraffic - Hong Kong Public Transport Explorer")
    logging.info("=" * 60)
    clear_cache()

    db_path = params["database"]["path"]
    logging.info("\n📊 Checking database...")
    if not os.path.exists(db_path):
        logging.warning(f"❌ Database not found at: {db_path}")
        logging.warning(
            "Run: python -m yuutraffic.data_updater --all --db-path data/01_raw/kmb_data.db"
        )
        return
    logging.info(f"✅ Database found: {os.path.getsize(db_path) / 1024 / 1024:.1f} MB")

    if params.get("schedule", {}).get("daily_update", {}).get("enabled", True):
        logging.info("\n🔄 Checking data updates...")
        try:
            if should_update_data():
                logging.info("📊 Data update required...")
                updater = KMBDataUpdater(db_path=db_path)
                db = KMBDatabaseManager(db_path=db_path)
                routes = updater.fetch_routes()
                if routes:
                    db.insert_routes(routes)
                    logging.info("   • Routes updated")
                stops = updater.fetch_stops()
                if stops:
                    db.insert_stops(stops)
                    logging.info("   • Stops updated")
                else:
                    logging.info(
                        "   • Stops skipped (API may be restricted; using existing data)"
                    )
                logging.info("✅ Data update completed")
            else:
                logging.info("📊 Data is up to date")
        except Exception as e:
            logging.warning(f"⚠️ Data update failed: {e}")

    port = params["app"]["port"]
    host = params["app"]["host"]
    app_path = os.path.join(project_root, "app.py")

    def _port_available(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return True
            except OSError:
                return False

    if not _port_available(port):
        for alt in range(port + 1, port + 10):
            if _port_available(alt):
                logging.info(f"   Port {port} in use, using {alt} instead")
                port = alt
                break

    logging.info("\n🚀 Launching Streamlit app...")
    logging.info(f"🔗 URL: http://{host}:{port}")
    logging.info("⏹️  Press Ctrl+C to stop")
    logging.info("-" * 60)

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                app_path,
                "--server.port",
                str(port),
                "--server.address",
                host,
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            check=True,
            cwd=project_root,
        )
    except KeyboardInterrupt:
        logging.info("\n👋 Stopped by user")
        clear_cache()
    except Exception as e:
        logging.error(f"❌ Error: {e}")
        logging.error(f"Try: streamlit run app.py --server.port {port}")


if __name__ == "__main__":
    main()
