#!/usr/bin/env python3
"""
Hong Kong KMB Route Map Launcher - Simplified Version
Clears cache and runs simplified streamlit app on port 8508
"""

import glob
import os
import subprocess
import sys


def clear_cache():
    """Clear streamlit cache and temporary files"""
    print("🧹 Clearing cache...")

    # Clear streamlit cache directory
    cache_dirs = [
        ".streamlit",
        "__pycache__",
        "*.pyc",
        "*.pyo",
        ".cache",
        "kmb_routes_cache.json",
        "kmb_data_cache.json",
    ]

    for cache_pattern in cache_dirs:
        if "*" in cache_pattern:
            # Handle wildcard patterns
            for file in glob.glob(cache_pattern, recursive=True):
                try:
                    os.remove(file)
                    print(f"   ✅ Removed {file}")
                except OSError:
                    pass
        else:
            # Handle directories and specific files
            if os.path.exists(cache_pattern):
                try:
                    if os.path.isdir(cache_pattern):
                        import shutil

                        shutil.rmtree(cache_pattern)
                        print(f"   ✅ Removed directory {cache_pattern}")
                    else:
                        os.remove(cache_pattern)
                        print(f"   ✅ Removed file {cache_pattern}")
                except OSError as e:
                    print(f"   ⚠️  Could not remove {cache_pattern}: {e}")


def main():
    """Main launcher function"""
    print("🚌 Hong Kong KMB Route Map - Simplified Launcher")
    print("=" * 60)

    # Clear cache first
    clear_cache()

    print("\n🚀 Launching simplified KMB route map...")
    print("📱 The app will open in your default web browser")
    print("🔗 URL: http://localhost:8508")
    print("⏹️  Press Ctrl+C to stop the application")
    print("🚌 Features: Route selection → Map display (no stats, no ETA)")
    print("-" * 60)

    try:
        # Launch the simplified streamlit app on port 8508
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "hk_transport_simplified.py",
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
        print("\n👋 KMB Route Map stopped by user")
        print("🧹 Cleaning up...")
        clear_cache()
    except Exception as e:
        print(f"❌ Error launching application: {e}")
        print("Try running manually:")
        print("  streamlit run hk_transport_simplified.py --server.port 8508")


if __name__ == "__main__":
    main()
