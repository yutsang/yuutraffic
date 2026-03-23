#!/usr/bin/env python3
"""
Hong Kong KMB Transport - Production Launcher
Launches the production-ready Kedro-based application
"""

import glob
import os
import shutil
import subprocess
import sys


def clear_cache():
    """Clear streamlit cache and temporary files"""
    print("🧹 Clearing cache and temporary files...")

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
                    print(f"   ✅ Removed {os.path.basename(file)}")
                except OSError:
                    pass
        else:
            # Handle directories
            if os.path.exists(pattern):
                try:
                    if os.path.isdir(pattern):
                        shutil.rmtree(pattern)
                        print(f"   ✅ Removed directory {pattern}")
                    else:
                        os.remove(pattern)
                        print(f"   ✅ Removed file {pattern}")
                except OSError as e:
                    print(f"   ⚠️  Could not remove {pattern}: {e}")


def check_database():
    """Check if database exists"""
    db_path = "data/01_raw/kmb_data.db"

    if os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        print(f"✅ Database found: {size_mb:.1f} MB")
        return True
    else:
        print(f"❌ Database not found at: {db_path}")
        return False


def main():
    """Main launcher function"""
    print("🚌 Hong Kong KMB Transport - Production Launcher")
    print("=" * 70)
    print("📱 Kedro-based production application")
    print("🎯 All routes, both directions, natural sorting")
    print("🗺️ OSM waypoint routing with progress tracking")
    print("🎨 Theme-adaptive responsive interface")
    print("-" * 70)

    # Clear cache
    clear_cache()

    # Check database
    print("\n📊 Checking database...")
    if not check_database():
        print("Please ensure the database is properly set up.")
        print("Run: python src/hk_kmb_transport/data_updater.py --all")
        return

    print("\n🚀 Launching production KMB Transport app...")
    print("📱 Opening in your default web browser")
    print("🔗 URL: http://localhost:8508")
    print("⏹️  Press Ctrl+C to stop the application")
    print("🔧 Production features:")
    print("   • Search functionality")
    print("   • Natural route sorting (1, 2, 3, 10, 11, 101...)")
    print("   • Both inbound/outbound directions")
    print("   • OSM routing with progress indicators")
    print("   • Theme-adaptive interface")
    print("   • Complete route coverage (788 routes)")
    print("-" * 70)

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
            ]
        )
    except KeyboardInterrupt:
        print("\n👋 Production KMB Transport stopped by user")
        print("🧹 Cleaning up...")
        clear_cache()
    except Exception as e:
        print(f"❌ Error launching application: {e}")
        print("Try running manually:")
        print(f"  streamlit run {app_path} --server.port 8508")


if __name__ == "__main__":
    main()
