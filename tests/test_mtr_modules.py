import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from yuutraffic.lrt_routing import find_light_rail_route
from yuutraffic.mtr_bus_geo import mtr_interpolate_lat_lng
from yuutraffic.mtr_client import (
    parse_light_rail_routes_csv,
    parse_rail_lines_csv,
    trains_for_planned_rail_direction,
)
from yuutraffic.mtr_layout import (
    build_station_layout_details,
    summarize_layout_payloads,
)
from yuutraffic.mtr_routing import (
    RouteSegment,
    estimate_mtr_journey_minutes,
    find_route,
)


def test_trains_for_planned_rail_direction_prefers_terminal_match():
    eta = {
        "UP": [{"dest": "AAA", "platform": "1", "minutes": "5"}],
        "DOWN": [{"dest": "BBB", "platform": "2", "minutes": "3"}],
    }
    picked = trains_for_planned_rail_direction(eta, "BBB")
    assert len(picked) == 1
    assert picked[0]["dest"] == "BBB"


def test_trains_for_planned_rail_direction_fallback_to_first_nonempty():
    eta = {
        "UP": [],
        "DOWN": [{"dest": "ZZZ", "platform": "1", "minutes": "1"}],
    }
    picked = trains_for_planned_rail_direction(eta, "")
    assert picked[0]["dest"] == "ZZZ"


def test_parse_rail_lines_csv():
    csv_text = """\ufeff"Line Code","Direction","Station Code","Station ID","Chinese Name","English Name","Sequence"
"TWL","DT","CEN","1","中環","Central",1
"TWL","DT","ADM","2","金鐘","Admiralty",2
"ISL","DT","ADM","2","金鐘","Admiralty",1
"ISL","DT","WAC","80","灣仔","Wan Chai",2
"""
    rows = parse_rail_lines_csv(csv_text)
    assert len(rows) == 4
    assert rows[0]["line_code"] == "TWL"
    assert rows[0]["station_code"] == "CEN"
    assert rows[0]["name_tc"] == "中環"


def test_parse_light_rail_routes_csv():
    csv_text = """\ufeff"Line Code","Direction","Stop Code","Stop ID","Chinese Name","English Name","Sequence"
"507","1","FEP","001","屯門碼頭","Tuen Mun Ferry Pier",1
"507","1","SHE","240","兆禧","Siu Hei",2
"507","2","SHE","240","兆禧","Siu Hei",1
"""
    rows = parse_light_rail_routes_csv(csv_text)
    assert len(rows) == 3
    assert rows[0]["route_no"] == "507"
    assert rows[0]["stop_id"] == "1"
    assert rows[1]["name_en"] == "Siu Hei"


def test_estimate_mtr_journey_minutes_single_rail_leg():
    segs = [
        RouteSegment(
            kind="rail",
            line_code="TWL",
            stations=["CEN", "ADM", "WAC"],
            terminal_code="WAC",
        ),
    ]
    breakdown, total = estimate_mtr_journey_minutes(segs, minutes_per_rail_stop=2.0)
    assert len(breakdown) == 1
    assert breakdown[0][2] == 4.0
    assert total == 4.0


def test_estimate_mtr_journey_minutes_two_rail_legs_adds_interchange():
    segs = [
        RouteSegment(
            kind="rail", line_code="TWL", stations=["CEN", "ADM"], terminal_code="ADM"
        ),
        RouteSegment(
            kind="rail", line_code="ISL", stations=["ADM", "WAC"], terminal_code="WAC"
        ),
    ]
    breakdown, total = estimate_mtr_journey_minutes(
        segs,
        minutes_per_rail_stop=2.0,
        interchange_minutes=3.0,
    )
    assert len(breakdown) == 2
    assert breakdown[0][2] == 2.0
    assert breakdown[1][2] == 5.0  # 2 + 3 interchange
    assert total == 7.0


def test_find_route_with_interchange():
    rows = [
        {
            "line_code": "TWL",
            "direction": "DT",
            "station_code": "CEN",
            "station_id": 1,
            "name_en": "Central",
            "name_tc": "中環",
            "sequence": 1,
        },
        {
            "line_code": "TWL",
            "direction": "DT",
            "station_code": "ADM",
            "station_id": 2,
            "name_en": "Admiralty",
            "name_tc": "金鐘",
            "sequence": 2,
        },
        {
            "line_code": "ISL",
            "direction": "DT",
            "station_code": "ADM",
            "station_id": 2,
            "name_en": "Admiralty",
            "name_tc": "金鐘",
            "sequence": 1,
        },
        {
            "line_code": "ISL",
            "direction": "DT",
            "station_code": "WAC",
            "station_id": 80,
            "name_en": "Wan Chai",
            "name_tc": "灣仔",
            "sequence": 2,
        },
    ]
    route = find_route(rows, "CEN", "WAC", transfer_penalty=4.0)
    assert route is not None
    assert route["interchanges"] == 1
    assert [segment.line_code for segment in route["rail_segments"]] == ["TWL", "ISL"]


def test_find_light_rail_route_with_transfer():
    rows = [
        {
            "route_no": "507",
            "direction": "1",
            "stop_code": "A",
            "stop_id": "1",
            "name_en": "Stop A",
            "name_tc": "甲",
            "sequence": 1,
        },
        {
            "route_no": "507",
            "direction": "1",
            "stop_code": "B",
            "stop_id": "2",
            "name_en": "Stop B",
            "name_tc": "乙",
            "sequence": 2,
        },
        {
            "route_no": "507",
            "direction": "1",
            "stop_code": "C",
            "stop_id": "3",
            "name_en": "Stop C",
            "name_tc": "丙",
            "sequence": 3,
        },
        {
            "route_no": "614",
            "direction": "1",
            "stop_code": "C",
            "stop_id": "3",
            "name_en": "Stop C",
            "name_tc": "丙",
            "sequence": 1,
        },
        {
            "route_no": "614",
            "direction": "1",
            "stop_code": "D",
            "stop_id": "4",
            "name_en": "Stop D",
            "name_tc": "丁",
            "sequence": 2,
        },
    ]
    route = find_light_rail_route(rows, "1", "4", transfer_penalty=3.0)
    assert route is not None
    assert route["interchanges"] == 1
    assert [segment.route_no for segment in route["segments"]] == ["507", "614"]


def test_unknown_mtr_bus_geometry_stays_unset():
    assert mtr_interpolate_lat_lng("UNKNOWN", 1, 3, "D") == (0.0, 0.0)


def test_summarize_layout_payloads():
    summary = summarize_layout_payloads(
        {
            "features": [
                {"properties": {"level_name_en": "Concourse"}},
                {"properties": {"level_name_en": "Platform"}},
            ]
        },
        {"features": [{"properties": {}}, {"properties": {}}]},
        {
            "features": [
                {"properties": {"amenity_category": "elevator"}},
                {"properties": {"amenity_category": "elevator"}},
                {"properties": {"amenity_category": "toilet"}},
            ]
        },
        {
            "features": [
                {"properties": {"occupant_name_en": "7-Eleven"}},
                {"properties": {"occupant_name_en": "Cafe"}},
            ]
        },
    )
    assert summary["level_count"] == 2
    assert summary["exit_count"] == 2
    assert summary["amenity_counts"]["elevator"] == 2
    assert summary["shop_count"] == 2


def test_build_station_layout_details_includes_guidance():
    layout = build_station_layout_details(
        {
            "levels": {
                "features": [
                    {
                        "properties": {
                            "level_id": "L1",
                            "level_name_en": "Concourse",
                            "level_name_zh": "大堂",
                            "level_short_name_en": "L1",
                            "level_ordinal": 1,
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [114.1, 22.3, 0],
                                    [114.2, 22.3, 0],
                                    [114.2, 22.4, 0],
                                    [114.1, 22.4, 0],
                                    [114.1, 22.3, 0],
                                ]
                            ],
                        },
                    }
                ]
            },
            "units": {
                "features": [
                    {
                        "properties": {
                            "unit_id": "U1",
                            "unit_category": "room",
                            "unit_name_en": "Hall",
                            "level_id": "L1",
                            "level_name_en": "Concourse",
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [114.11, 22.31, 0],
                                    [114.12, 22.31, 0],
                                    [114.12, 22.32, 0],
                                    [114.11, 22.32, 0],
                                    [114.11, 22.31, 0],
                                ]
                            ],
                        },
                    }
                ]
            },
            "openings": {
                "features": [
                    {
                        "properties": {
                            "opening_id": "O1",
                            "opening_name": "Exit A",
                            "opening_category": "pedestrian",
                            "level_id": "L1",
                            "level_name_en": "Concourse",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[114.105, 22.305, 0], [114.106, 22.306, 0]],
                        },
                    }
                ]
            },
            "amenities": {
                "features": [
                    {
                        "properties": {
                            "amenity_id": "A1",
                            "amenity_name_en": "Escalator",
                            "amenity_category": "escalator",
                            "level_id": "L1",
                            "level_name_en": "Concourse",
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [114.106, 22.306, 0],
                        },
                    }
                ]
            },
            "occupants": {"features": []},
        }
    )
    assert layout["levels_meta"][0]["level_id"] == "L1"
    assert layout["units_meta"][0]["unit_id"] == "U1"
    assert layout["nearest_openings"][0]["opening_label"] == "Exit A"
