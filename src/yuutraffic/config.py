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
        "route_geometry_dir": "data/02_intermediate/route_geometry",
        "route_geometry_cache": "data/02_intermediate/route_geometry_cache.json",
        "schedule": {"daily_update": {"enabled": True, "time": "02:00"}},
        "map": {
            "center": {"lat": 22.3193, "lng": 114.1694},
            "default_zoom": 11,
            "auto_zoom": {"enabled": True, "route_zoom": 14, "stop_zoom": 16},
            "tiles": "OpenStreetMap",
        },
        "api": {
            "kmb_base_url": "https://data.etabus.gov.hk/v1/transport/kmb",
            "citybus_base_url": "https://rt.data.gov.hk/v2/transport/citybus",
            "gmb_base_url": "https://data.etagmb.gov.hk",
            "mtr_bus_schedule_url": "https://rt.data.gov.hk/v1/transport/mtr/bus/getSchedule",
            "mtr_next_train_url": "https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php",
            "mtr_light_rail_schedule_url": "https://rt.data.gov.hk/v1/transport/mtr/lrt/getSchedule",
            "mtr_light_rail_routes_stops_url": "https://opendata.mtr.com.hk/data/light_rail_routes_and_stops.csv",
            "mtr_lines_stations_url": "https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv",
            "mtr_indoor_map_base_url": "https://mapapi.hkmapservice.gov.hk/ogc/wfs/indoor",
            "nominatim_search_url": "https://nominatim.openstreetmap.org/search",
            "osm_routing_url": "http://router.project-osrm.org/route/v1/walking",
        },
        "osm": {"max_waypoints": 25, "timeout": 10},
        "route_types": {
            "circular": ["CIRCULAR", "(CIRCULAR)", "CIRCLE"],
            "special": ["X", "S", "P", "A", "E", "N", "R"],
        },
        "trip_planner": {
            "walk_minutes": 15,
            "walking_speed_kmh": 5,
            "max_catchment_stop_ids": 400,
            "max_transfers": 3,
            "top_results": 5,
            "max_direct_results": 3,
            "routing_transfer_penalty": 8,
            "routing_cost_slack": 4,
            "routing_max_alternatives": 80,
            "avg_bus_speed_kmh": 17,
            "minutes_per_transfer": 4,
            "fallback_minutes_per_bus_hop": 2.4,
            "results_max_extra_minutes_vs_best": 22,
            "results_max_ratio_vs_best": 1.38,
        },
        "mtr": {
            "routing_transfer_penalty": 4.0,
            "light_rail_transfer_penalty": 3.0,
            "rail_minutes_per_stop": 2.5,
            "walk_leg_minutes": 5.0,
            "interchange_minutes": 3.0,
        },
        "ui": {"show_progress_bars": True},
        "data_update": {
            "skip_transport_api_if_catalog_complete": True,
            "catalog_min_routes": 500,
            "catalog_min_stops": 500,
            "catalog_min_route_stops": 5000,
            "catalog_compare_mtr": True,
        },
    }
