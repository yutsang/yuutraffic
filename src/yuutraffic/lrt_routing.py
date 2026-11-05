"""
Light Rail routing helpers based on official route-stop sequences.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class LRSegment:
    kind: str
    route_no: str
    stops: list[str]

    @property
    def from_stop(self) -> str:
        return self.stops[0]

    @property
    def to_stop(self) -> str:
        return self.stops[-1]


def build_stop_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stops: dict[str, dict[str, Any]] = {}
    for row in rows:
        stop_id = row["stop_id"]
        stops.setdefault(
            stop_id,
            {
                "stop_id": stop_id,
                "stop_code": row.get("stop_code", ""),
                "name_en": row.get("name_en", stop_id),
                "name_tc": row.get("name_tc", ""),
            },
        )
    return stops


def build_route_sequences(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["route_no"], row["direction"])].append(row)
    out: dict[tuple[str, str], list[str]] = {}
    for key, group in grouped.items():
        group.sort(
            key=lambda item: (int(item.get("sequence", 0) or 0), item["stop_id"])
        )
        seq: list[str] = []
        for item in group:
            stop_id = str(item["stop_id"])
            if not seq or seq[-1] != stop_id:
                seq.append(stop_id)
        out[key] = seq
    return out


def stop_options(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    stops = build_stop_index(rows)
    options = [
        {
            "id": stop_id,
            "label": (
                f"{meta['name_en']} / {meta['name_tc']} [{stop_id}]"
                if meta.get("name_tc")
                else f"{meta['name_en']} [{stop_id}]"
            ),
            "name_en": str(meta.get("name_en", stop_id)),
            "name_tc": str(meta.get("name_tc", "")),
        }
        for stop_id, meta in stops.items()
    ]
    options.sort(key=lambda item: item["name_en"].lower())
    return options


def build_adjacency(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sequences = build_route_sequences(rows)
    seen_edges: set[tuple[str, str, str]] = set()
    for (route_no, _direction), sequence in sequences.items():
        for left, right in zip(sequence, sequence[1:]):
            edge_key = (min(left, right), max(left, right), route_no)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            for src, dst in ((left, right), (right, left)):
                adjacency[src].append(
                    {
                        "to": dst,
                        "route_no": route_no,
                        "kind": "light_rail",
                        "weight": 1.0,
                    }
                )
    return adjacency


def summarize_segments(
    stop_path: list[str], edge_path: list[dict[str, Any]]
) -> list[LRSegment]:
    if not stop_path or len(stop_path) == 1 or not edge_path:
        return []
    segments: list[LRSegment] = []
    current: LRSegment | None = None
    for idx, edge in enumerate(edge_path):
        src = stop_path[idx]
        dst = stop_path[idx + 1]
        route_no = str(edge.get("route_no", "") or "")
        kind = str(edge.get("kind", "light_rail") or "light_rail")
        if current and current.kind == kind and current.route_no == route_no:
            current.stops.append(dst)
            continue
        current = LRSegment(kind=kind, route_no=route_no, stops=[src, dst])
        segments.append(current)
    return segments


def find_light_rail_route(
    rows: list[dict[str, Any]],
    origin_stop_id: str,
    dest_stop_id: str,
    *,
    transfer_penalty: float = 3.0,
) -> dict[str, Any] | None:
    origin = str(origin_stop_id or "").strip()
    dest = str(dest_stop_id or "").strip()
    if not origin or not dest or origin == dest:
        return None
    adjacency = build_adjacency(rows)
    if origin not in adjacency or dest not in adjacency:
        return None
    stops = build_stop_index(rows)

    State = tuple[str, str]
    start: State = (origin, "")
    dist: dict[State, float] = {start: 0.0}
    parent: dict[State, tuple[State | None, dict[str, Any] | None]] = {
        start: (None, None)
    }
    heap: list[tuple[float, str, str]] = [(0.0, origin, "")]
    best_goal: State | None = None

    while heap:
        cost, stop_id, current_route = heapq.heappop(heap)
        state = (stop_id, current_route)
        if cost > dist.get(state, float("inf")):
            continue
        if stop_id == dest:
            best_goal = state
            break
        for edge in adjacency.get(stop_id, []):
            next_route = str(edge.get("route_no", "") or "")
            extra = float(edge.get("weight", 1.0) or 1.0)
            if current_route and current_route != next_route:
                extra += transfer_penalty
            next_state: State = (edge["to"], next_route)
            next_cost = cost + extra
            if next_cost >= dist.get(next_state, float("inf")):
                continue
            dist[next_state] = next_cost
            parent[next_state] = (state, edge)
            heapq.heappush(heap, (next_cost, next_state[0], next_state[1]))

    if best_goal is None:
        return None

    edge_path: list[dict[str, Any]] = []
    stop_path: list[str] = []
    cur: State | None = best_goal
    while cur is not None:
        stop_path.append(cur[0])
        prev_state, edge = parent[cur]
        if edge is not None:
            edge_path.append(edge)
        cur = prev_state
    stop_path.reverse()
    edge_path.reverse()
    segments = summarize_segments(stop_path, edge_path)
    return {
        "stops": stops,
        "stop_path": stop_path,
        "segments": segments,
        "total_stops": max(0, len(stop_path) - 1),
        "interchanges": max(0, len(segments) - 1),
        "score": round(dist[best_goal], 2),
    }
