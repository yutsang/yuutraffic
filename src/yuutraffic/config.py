"""Simple YAML configuration loader. Replaces Kedro OmegaConfigLoader."""

from pathlib import Path

import yaml


def load_config() -> dict:
    """Load parameters from conf/base/parameters.yml."""
    project_root = Path(__file__).resolve().parent.parent.parent
    conf_path = project_root / "conf" / "base" / "parameters.yml"

    if not conf_path.exists():
        return _default_config()

    with open(conf_path) as f:
        data = yaml.safe_load(f)

    return data if data else _default_config()


def _default_config() -> dict:
    """Return default configuration when file is missing."""
    return {
        "app": {"port": 8508, "host": "localhost"},
        "database": {"path": "data/01_raw/kmb_data.db"},
        "route_geometry_cache": "data/02_intermediate/route_geometry_cache.json",
        "schedule": {"daily_update": {"enabled": True, "time": "02:00"}},
        "map": {
            "center": {"lat": 22.3193, "lng": 114.1694},
            "default_zoom": 11,
            "auto_zoom": {"enabled": True, "route_zoom": 14, "stop_zoom": 16},
            "tiles": "OpenStreetMap",
        },
        "api": {"osm_routing_url": "http://router.project-osrm.org/route/v1/walking"},
        "osm": {"max_waypoints": 25, "timeout": 10},
        "route_types": {
            "circular": ["CIRCULAR", "(CIRCULAR)", "CIRCLE"],
            "special": ["X", "S", "P", "A", "E", "N", "R"],
        },
        "ui": {"show_progress_bars": True},
    }
