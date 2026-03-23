"""
Railway routing helpers for MTR lines.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .mtr_client import LINE_NAMES

LINE_COLORS: dict[str, str] = {
    "AEL": "#00888a",
    "DRL": "#ef7d00",
    "EAL": "#5eb6e4",
    "ISL": "#0075c2",
    "KTL": "#00a040",
    "SIL": "#b5bd00",
    "TCL": "#f3982d",
    "TKL": "#7e3f98",
    "TML": "#9a3b26",
    "TWL": "#e31b23",
    "WALK": "#4b5563",
}

WALK_LINKS: dict[frozenset[str], tuple[str, str]] = {
    frozenset({"CEN", "HOK"}): ("Central/Hong Kong paid-area walk", "中環／香港站步行"),
    frozenset({"TST", "ETS"}): (
        "Tsim Sha Tsui/East Tsim Sha Tsui walk",
        "尖沙咀／尖東步行",
    ),
}


@dataclass
class RouteSegment:
    kind: str
    line_code: str
    stations: list[str]
    terminal_code: str | None = None

    @property
    def from_station(self) -> str:
        return self.stations[0]

    @property
    def to_station(self) -> str:
        return self.stations[-1]


def build_station_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stations: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["station_code"]
        stations.setdefault(
            code,
            {
                "station_code": code,
                "station_id": row.get("station_id"),
                "name_en": row.get("name_en", code),
                "name_tc": row.get("name_tc", ""),
            },
        )
    return stations


def build_direction_sequences(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["line_code"], row["direction"])].append(row)
    out: dict[tuple[str, str], list[str]] = {}
    for key, group in grouped.items():
        group.sort(
            key=lambda item: (int(item.get("sequence", 0) or 0), item["station_code"])
        )
        out[key] = [item["station_code"] for item in group]
    return out


def build_adjacency(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sequences = build_direction_sequences(rows)
    seen_edges: set[tuple[str, str, str]] = set()
    for (line_code, _direction), sequence in sequences.items():
        for left, right in zip(sequence, sequence[1:]):
            edge_key = (min(left, right), max(left, right), line_code)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            for src, dst in ((left, right), (right, left)):
                adjacency[src].append(
                    {
                        "to": dst,
                        "line_code": line_code,
                        "kind": "rail",
                        "weight": 1.0,
                    }
                )
    for pair, _label in WALK_LINKS.items():
        left, right = sorted(pair)
        for src, dst in ((left, right), (right, left)):
            adjacency[src].append(
                {
                    "to": dst,
                    "line_code": "WALK",
                    "kind": "walk",
                    "weight": 2.0,
                }
            )
    return adjacency


def station_options(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    stations = build_station_index(rows)
    options = [
        {
            "code": code,
            "label": (
                f"{meta['name_en']} / {meta['name_tc']} [{code}]"
                if meta.get("name_tc")
                else f"{meta['name_en']} [{code}]"
            ),
            "name_en": str(meta.get("name_en", code)),
            "name_tc": str(meta.get("name_tc", "")),
        }
        for code, meta in stations.items()
    ]
    options.sort(key=lambda item: item["name_en"].lower())
    return options


def _infer_terminal_code(
    line_code: str,
    first_station: str,
    second_station: str,
    direction_sequences: dict[tuple[str, str], list[str]],
) -> str | None:
    for (seq_line, _direction), sequence in direction_sequences.items():
        if seq_line != line_code:
            continue
        for left, right in zip(sequence, sequence[1:]):
            if left == first_station and right == second_station:
                return sequence[-1]
    return None


def summarize_segments(
    station_path: list[str],
    edge_path: list[dict[str, Any]],
    direction_sequences: dict[tuple[str, str], list[str]],
) -> list[RouteSegment]:
    if not station_path or len(station_path) == 1 or not edge_path:
        return []
    segments: list[RouteSegment] = []
    current: RouteSegment | None = None
    for idx, edge in enumerate(edge_path):
        src = station_path[idx]
        dst = station_path[idx + 1]
        line_code = str(edge.get("line_code", "") or "")
        kind = str(edge.get("kind", "rail") or "rail")
        if current and current.kind == kind and current.line_code == line_code:
            current.stations.append(dst)
            continue
        current = RouteSegment(kind=kind, line_code=line_code, stations=[src, dst])
        segments.append(current)
    for segment in segments:
        if segment.kind == "rail" and len(segment.stations) >= 2:
            segment.terminal_code = _infer_terminal_code(
                segment.line_code,
                segment.stations[0],
                segment.stations[1],
                direction_sequences,
            )
    return segments


def find_route(
    rows: list[dict[str, Any]],
    origin_code: str,
    dest_code: str,
    *,
    transfer_penalty: float = 4.0,
) -> dict[str, Any] | None:
    """Find a simple best railway route using hop count plus transfer penalty."""
    origin = (origin_code or "").strip().upper()
    dest = (dest_code or "").strip().upper()
    if not origin or not dest or origin == dest:
        return None
    adjacency = build_adjacency(rows)
    if origin not in adjacency or dest not in adjacency:
        return None
    direction_sequences = build_direction_sequences(rows)
    stations = build_station_index(rows)

    State = tuple[str, str]
    start: State = (origin, "")
    dist: dict[State, float] = {start: 0.0}
    parent: dict[State, tuple[State | None, dict[str, Any] | None]] = {
        start: (None, None)
    }
    heap: list[tuple[float, str, str]] = [(0.0, origin, "")]
    best_goal: State | None = None

    while heap:
        cost, station, current_line = heapq.heappop(heap)
        state = (station, current_line)
        if cost > dist.get(state, float("inf")):
            continue
        if station == dest:
            best_goal = state
            break
        for edge in adjacency.get(station, []):
            next_line = str(edge.get("line_code", "") or "")
            extra = float(edge.get("weight", 1.0) or 1.0)
            if (
                edge.get("kind") == "rail"
                and current_line
                and current_line != next_line
            ):
                extra += transfer_penalty
            next_state: State = (
                edge["to"],
                next_line if edge.get("kind") == "rail" else current_line,
            )
            next_cost = cost + extra
            if next_cost >= dist.get(next_state, float("inf")):
                continue
            dist[next_state] = next_cost
            parent[next_state] = (state, edge)
            heapq.heappush(heap, (next_cost, next_state[0], next_state[1]))
    if best_goal is None:
        return None

    edge_path: list[dict[str, Any]] = []
    station_path: list[str] = []
    cur: State | None = best_goal
    while cur is not None:
        station_path.append(cur[0])
        prev_state, edge = parent[cur]
        if edge is not None:
            edge_path.append(edge)
        cur = prev_state
    station_path.reverse()
    edge_path.reverse()
    segments = summarize_segments(station_path, edge_path, direction_sequences)
    rail_segments = [segment for segment in segments if segment.kind == "rail"]
    return {
        "stations": stations,
        "station_path": station_path,
        "segments": segments,
        "rail_segments": rail_segments,
        "total_stops": max(0, len(station_path) - 1),
        "interchanges": max(0, len(rail_segments) - 1),
        "score": round(dist[best_goal], 2),
    }


def line_display(line_code: str) -> tuple[str, str]:
    return LINE_NAMES.get(line_code, (line_code, line_code))


def estimate_mtr_journey_minutes(
    segments: list[RouteSegment],
    *,
    minutes_per_rail_stop: float = 2.5,
    walk_leg_minutes: float = 5.0,
    interchange_minutes: float = 3.0,
) -> tuple[list[tuple[str, str, float]], float]:
    """
    Heuristic travel-time estimate for a planned MTR journey.

    Returns a list of (segment title, detail line, minutes) and total minutes.
    Rail legs use (number of station hops) * minutes_per_rail_stop; paid-area walks
    use walk_leg_minutes; each rail leg after the first adds interchange_minutes.
    """
    breakdown: list[tuple[str, str, float]] = []
    total = 0.0
    rail_leg_index = 0
    for segment in segments:
        if segment.kind == "walk":
            start = segment.from_station
            end = segment.to_station
            label = "Walk"
            en, _tc = WALK_LINKS.get(frozenset({start, end}), (f"{start} → {end}", ""))
            detail = en if en else f"{start} → {end}"
            m = float(walk_leg_minutes)
        else:
            hops = max(0, len(segment.stations) - 1)
            m = hops * float(minutes_per_rail_stop)
            if rail_leg_index > 0:
                m += float(interchange_minutes)
            rail_leg_index += 1
            en, _tc = line_display(segment.line_code)
            label = f"{segment.line_code} · {en}"
            detail = (
                f"{segment.from_station} → {segment.to_station} · {hops} hop(s)"
                if hops
                else f"{segment.from_station} → {segment.to_station}"
            )
        breakdown.append((label, detail, round(m, 1)))
        total += m
    return breakdown, round(total, 1)
