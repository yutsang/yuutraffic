#!/usr/bin/env python3
"""
Hong Kong KMB Transport - Production Launcher
Launches the production-ready Kedro-based application
"""

import glob
import logging
import os
import shutil
import subprocess
import sys

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


def check_database():
    """Check if database exists"""
    db_path = "data/01_raw/kmb_data.db"

    if os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        logging.info(f"✅ Database found: {size_mb:.1f} MB")
        return True
    else:
        logging.error(f"❌ Database not found at: {db_path}")
        return False


def main():
    """Main launcher function"""
    logging.info("🚌 Hong Kong KMB Transport - Production Launcher")
    logging.info("=" * 70)
    logging.info("📱 Kedro-based production application")
    logging.info("🎯 All routes, both directions, natural sorting")
    logging.info("🗺️ OSM waypoint routing with progress tracking")
    logging.info("🎨 Theme-adaptive responsive interface")
    logging.info("-" * 70)

    # Clear cache
    clear_cache()

    # Check database
    logging.info("\n📊 Checking database...")
    if not check_database():
        logging.info("Please ensure the database is properly set up.")
        logging.info("Run: python src/hk_kmb_transport/data_updater.py --all")
        return

    logging.info("\n🚀 Launching production KMB Transport app...")
    logging.info("📱 Opening in your default web browser")
    logging.info("🔗 URL: http://localhost:8508")
    logging.info("⏹️  Press Ctrl+C to stop the application")
    logging.info("🔧 Production features:")
    logging.info("   • Search functionality")
    logging.info("   • Natural route sorting (1, 2, 3, 10, 11, 101...)")
    logging.info("   • Both inbound/outbound directions")
    logging.info("   • OSM routing with progress indicators")
    logging.info("   • Theme-adaptive interface")
    logging.info("   • Complete route coverage (788 routes)")
    logging.info("-" * 70)

    try:
        # Launch the production Streamlit app
        app_path = "src/hk_kmb_transport/kmb_app_production.py"

        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                app_path,
                "--server.port",
                "8508",
                "--server.address",
                "localhost",
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
        logging.info("\n👋 Production KMB Transport stopped by user")
        logging.info("🧹 Cleaning up...")
        clear_cache()
    except Exception as e:
        logging.error(f"❌ Error launching application: {e}")
        logging.info("Try running manually:")
        logging.info(f"  streamlit run {app_path} --server.port 8508")


if __name__ == "__main__":
    main()
