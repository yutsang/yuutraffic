#!/usr/bin/env python3
"""
Download Hong Kong map tiles for offline/faster loading.
Run this script while online, then serve tiles locally:
  python -m http.server 8000 --directory data/tiles

Add to conf/base/parameters.yml:
  map:
    tiles_url: "http://localhost:8000/{z}/{x}/{y}.png"
"""
import math
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

# Hong Kong bounding box (lat, lng)
HK_MIN_LAT, HK_MAX_LAT = 22.15, 22.60
HK_MIN_LNG, HK_MAX_LNG = 113.82, 114.45

# Tile server (CartoDB - no API key, good for HK)
TILE_URL = "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "tiles"


def latlng_to_tile(lat: float, lng: float, zoom: int) -> tuple[int, int]:
    """Convert lat/lng to tile x,y at given zoom."""
    n = 2 ** zoom
    x = int((lng + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n)
    return x, y


def get_tile_bounds(zoom: int) -> tuple[int, int, int, int]:
    """Get tile x,y range for HK bbox at zoom level. Returns (x_min, y_min, x_max, y_max)."""
    x_min, y_n = latlng_to_tile(HK_MAX_LAT, HK_MIN_LNG, zoom)  # NW
    x_max, y_s = latlng_to_tile(HK_MIN_LAT, HK_MAX_LNG, zoom)  # SE (y_s > y_n in tile coords)
    return x_min, min(y_n, y_s), x_max, max(y_n, y_s)


def download_tiles(zoom_min: int = 10, zoom_max: int = 15) -> int:
    """Download tiles for HK at zoom levels zoom_min to zoom_max."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for z in range(zoom_min, zoom_max + 1):
        x_min, y_min, x_max, y_max = get_tile_bounds(z)
        count = (x_max - x_min + 1) * (y_max - y_min + 1)
        print(f"Zoom {z}: {count} tiles ({x_min}-{x_max}, {y_min}-{y_max})")
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                out_path = OUTPUT_DIR / str(z) / str(x) / f"{y}.png"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if out_path.exists():
                    continue
                url = TILE_URL.format(z=z, x=x, y=y)
                try:
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        out_path.write_bytes(r.content)
                        total += 1
                except Exception:
                    pass
                time.sleep(0.05)  # Be nice to the server
    return total


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Download HK map tiles for offline use")
    ap.add_argument("--min-zoom", type=int, default=10)
    ap.add_argument("--max-zoom", type=int, default=14)
    args = ap.parse_args()
    print(f"Downloading tiles to {OUTPUT_DIR}")
    print(f"Zoom levels {args.min_zoom}-{args.max_zoom}")
    n = download_tiles(args.min_zoom, args.max_zoom)
    print(f"Downloaded {n} new tiles.")
    print("\nTo use locally, add to conf/base/parameters.yml:")
    print('  map:')
    print('    tiles_url: "http://localhost:8000/{z}/{x}/{y}.png"')
    print("\nThen run: python -m http.server 8000 --directory data/tiles")


if __name__ == "__main__":
    main()
