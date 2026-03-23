#!/usr/bin/env python3
"""
Traffic ETA - Production Launcher
Launches the production-ready Traffic ETA application with all enhancements
"""

import glob
import logging
import os
import shutil
import subprocess
import sys

from kedro.config import OmegaConfigLoader

# Import modules that may not be available at startup
try:
    from data_updater import KMBDataUpdater
    from database_manager import KMBDatabaseManager
    from pipelines.web_app.nodes import should_update_data
except ImportError:
    # These will be imported when needed
    pass

logging.basicConfig(level=logging.INFO, format="%(message)s")


def clear_cache():
    """Clear streamlit cache and temporary files"""
    logging.info("🧹 Clearing cache and temporary files...")

    # Cache patterns to clear
    cache_patterns = [
        ".streamlit",
        "__pycache__",
        "*.pyc",
        "*.pyo",
        ".cache",
        "*.cache.json",
    ]

    for pattern in cache_patterns:
        if "*" in pattern:
            # Handle wildcard patterns
            for file in glob.glob(f"**/{pattern}", recursive=True):
                try:
                    os.remove(file)
                    logging.info(f"   ✅ Removed {os.path.basename(file)}")
                except OSError:
                    pass
        elif os.path.exists(pattern):
            # Handle directories
            try:
                if os.path.isdir(pattern):
                    shutil.rmtree(pattern)
                    logging.info(f"   ✅ Removed directory {pattern}")
                else:
                    os.remove(pattern)
                    logging.info(f"   ✅ Removed file {pattern}")
            except OSError as e:
                logging.warning(f"   ⚠️  Could not remove {pattern}: {e}")


def load_configuration():
    """Load application configuration"""
    try:
        conf_path = os.path.join(os.path.dirname(__file__), "..", "..", "conf")
        conf_loader = OmegaConfigLoader(conf_source=conf_path)
        return conf_loader["parameters"]
    except Exception as e:
        logging.warning(f"⚠️ Could not load configuration: {e}")
        # Return default config
        return {
            "app": {"port": 8508, "host": "localhost"},
            "database": {"path": "data/01_raw/kmb_data.db"},
        }


def check_database(params):
    """Check if database exists and is accessible"""
    db_path = params["database"]["path"]

    if os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        logging.info(f"✅ Database found: {size_mb:.1f} MB")
        return True
    else:
        logging.warning(f"❌ Database not found at: {db_path}")
        return False


def check_first_run():
    """Check if this is the first run"""
    first_run_file = "data/.first_run_complete"
    if not os.path.exists(first_run_file):
        logging.info("🚀 First run detected - will perform initial setup")
        return True
    return False


def setup_data_update(params):
    """Setup data update process if needed"""
    if should_update_data():
        logging.info("📊 Data update required...")
        try:
            # Import and run data update
            updater = KMBDataUpdater()
            db_manager = KMBDatabaseManager()

            logging.info("   • Updating routes...")
            routes = updater.fetch_routes()
            if routes:
                db_manager.insert_routes(routes)

            logging.info("   • Updating stops...")
            stops = updater.fetch_stops()
            if stops:
                db_manager.insert_stops(stops)

            logging.info("✅ Data update completed")
            return True
        except Exception as e:
            logging.warning(f"⚠️ Data update failed: {e}")
            return False
    else:
        logging.info("📊 Data is up to date")
        return True


def main():
    """Main launcher function"""
    logging.info("🚌 Traffic ETA - Production Launcher")
    logging.info("=" * 70)
    logging.info("🌟 Enhanced Hong Kong Public Transport Explorer")
    logging.info("🎯 Complete route coverage with dual directions")
    logging.info("🗺️ OSM routing with auto-zoom and center controls")
    logging.info("🏷️ Route type classification (Express, Night, Circular)")
    logging.info("🔍 Enhanced search with depot names")
    logging.info("-" * 70)

    # Load configuration
    params = load_configuration()

    # Clear cache
    clear_cache()

    # Check database
    logging.info("\n📊 Checking database...")
    if not check_database(params):
        logging.warning("Please ensure the database is properly set up.")
        logging.warning("Run: python src/traffic_eta/data_updater.py --all")
        return

    # Setup data update if configured
    if params.get("schedule", {}).get("daily_update", {}).get("enabled", True):
        logging.info("\n🔄 Checking data updates...")
        setup_data_update(params)

    logging.info("\n🚀 Launching Traffic ETA application...")
    logging.info("📱 Opening in your default web browser")
    logging.info(f"🔗 URL: http://{params['app']['host']}:{params['app']['port']}")
    logging.info("⏹️  Press Ctrl+C to stop the application")
    logging.info("🔧 Enhanced features:")
    logging.info("   • Dual direction search with depot names")
    logging.info("   • Route type classification and badges")
    logging.info("   • Auto-zoom maps with center button")
    logging.info("   • Enhanced search and filtering")
    logging.info("   • First-run setup and daily updates")
    logging.info("   • Complete route coverage (788 routes)")
    logging.info("-" * 70)

    try:
        # Launch the Traffic ETA Streamlit app
        app_path = "src/traffic_eta/traffic_eta_app.py"
        port = params["app"]["port"]
        host = params["app"]["host"]

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
                "--server.runOnSave",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            check=True,
        )
    except KeyboardInterrupt:
        logging.info("\n👋 Traffic ETA stopped by user")
        logging.info("🧹 Cleaning up...")
        clear_cache()
    except Exception as e:
        logging.error(f"❌ Error launching application: {e}")
        logging.error("Try running manually:")
        logging.error(f"  streamlit run {app_path} --server.port {port}")


if __name__ == "__main__":
    main()
