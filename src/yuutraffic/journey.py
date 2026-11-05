"""
Point-to-point bus journey suggestions from SQLite route_stops (direct and multi-transfer).
Supports multiple equivalent stop IDs per end (same physical stop, different operators / IDs).
"""

from __future__ import annotations

import heapq
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Leg:
    route_key: str
    route_id: str
    company: str
    direction: int
    from_stop: str
    to_stop: str
    stops_board_to_alight: list[str]


@dataclass
class Journey:
    legs: list[Leg]
    transfer_stop: str | None = (
        None  # first transfer point (legacy); prefer legs for multi-transfer
    )
    routing_cost: float | None = (
        None  # hop + transfer penalty score from Dijkstra (lower is better)
    )

    @property
    def transfer_stops(self) -> list[str]:
        """Alight points between legs (same physical stop may repeat as ID variants)."""
        if len(self.legs) < 2:
            return []
        return [self.legs[i].to_stop for i in range(len(self.legs) - 1)]


def _is_circular_destination(dest_en: str, dest_tc: str) -> bool:
    hay = f"{(dest_en or '').upper()} {(dest_tc or '').strip()}"
    return "CIRCULAR" in hay or "CIRCLE" in hay or "循環" in hay


def _is_terminus_stop(name_en: str, name_tc: str) -> bool:
    en = (name_en or "").upper()
    tc = (name_tc or "").strip()
    return "BUS TERMINUS" in en or "總站" in tc


def load_stop_cluster_maps(
    db_path: str, precision: int = 4
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """
    Group stops that share the same rounded lat/lng (same pole / platform area).
    Stops without coordinates get a singleton cluster per stop_id.
    """
    stop_to_cluster: dict[str, str] = {}
    cluster_members: dict[str, set[str]] = defaultdict(set)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("""
                SELECT stop_id, lat, lng FROM stops
                """)
            rows = cur.fetchall()
    except sqlite3.Error:
        return {}, {}

    for sid, la, ln in rows:
        sid = str(sid)
        try:
            lat, lng = float(la), float(ln)
        except (TypeError, ValueError):
            lat, lng = 0.0, 0.0
        if lat == 0 and lng == 0:
            ck = f"id:{sid}"
        else:
            ck = f"{round(lat, precision):.{precision}f},{round(lng, precision):.{precision}f}"
        stop_to_cluster[sid] = ck
        cluster_members[ck].add(sid)

    return stop_to_cluster, dict(cluster_members)


def _cluster_set(
    stop_id: str,
    stop_to_cluster: dict[str, str],
    cluster_members: dict[str, set[str]],
) -> set[str]:
    ck = stop_to_cluster.get(stop_id)
    if ck is None:
        return {stop_id}
    return set(cluster_members.get(ck, {stop_id}))


def load_route_segments(db_path: str) -> list[dict[str, Any]]:
    """One segment per (route_key, direction): ordered stop_ids."""
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("""
                SELECT COALESCE(rs.route_key, rs.route_id), rs.route_id, rs.direction, rs.sequence,
                       rs.stop_id, COALESCE(r.company, ''),
                       COALESCE(s.stop_name_en, ''), COALESCE(s.stop_name_tc, ''),
                       COALESCE(r.destination_en, ''), COALESCE(r.destination_tc, '')
                FROM route_stops rs
                LEFT JOIN routes r ON r.route_key = COALESCE(rs.route_key, rs.route_id)
                LEFT JOIN stops s ON s.stop_id = rs.stop_id
                ORDER BY 1, rs.direction, rs.sequence
                """)
            rows = cur.fetchall()
    except sqlite3.Error:
        return []
    by_seq: dict[tuple[str, int], list[tuple[int, str, str, str]]] = defaultdict(list)
    meta: dict[tuple[str, int], tuple[str, str, str, str]] = {}
    for rk, rid, di, seq, sid, c, sn_en, sn_tc, dest_en, dest_tc in rows:
        key = (str(rk), int(di))
        by_seq[key].append(
            (int(seq or 0), str(sid), str(sn_en or ""), str(sn_tc or ""))
        )
        meta[key] = (str(rid), str(c or ""), str(dest_en or ""), str(dest_tc or ""))
    segments: list[dict[str, Any]] = []
    for key, items in by_seq.items():
        items.sort(key=lambda x: x[0])
        rk, di = key
        rid, c, dest_en, dest_tc = meta[key]
        if _is_circular_destination(dest_en, dest_tc) and len(items) > 1:
            last = items[-1]
            first = items[0]
            if _is_terminus_stop(last[2], last[3]) and not _is_terminus_stop(
                first[2], first[3]
            ):
                items = [last] + items[:-1]
        stops = [s for _, s, _, _ in items]
        rk, di = key
        segments.append(
            {
                "route_key": rk,
                "route_id": rid,
                "direction": di,
                "stops": stops,
                "company": c,
            }
        )
    return segments


def _first_board_index(seq: list[str], origin_ids: list[str]) -> int | None:
    idxs = [seq.index(o) for o in origin_ids if o in seq]
    return min(idxs) if idxs else None


def _first_alight_after(
    seq: list[str], board_idx: int, dest_ids: list[str]
) -> int | None:
    """Smallest index > board_idx where stop is one of dest_ids."""
    cands = [seq.index(d) for d in dest_ids if d in seq and seq.index(d) > board_idx]
    return min(cands) if cands else None


def _same_segment(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["route_key"] == b["route_key"] and int(a["direction"]) == int(
        b["direction"]
    )


def _make_leg(seg: dict[str, Any], i_board: int, i_alight: int, seq: list[str]) -> Leg:
    return Leg(
        route_key=seg["route_key"],
        route_id=seg["route_id"],
        company=seg["company"],
        direction=seg["direction"],
        from_stop=seq[i_board],
        to_stop=seq[i_alight],
        stops_board_to_alight=seq[i_board : i_alight + 1],
    )


def _journey_dedup_key(j: Journey) -> tuple[tuple[str, str, int, str, str], ...]:
    return tuple(
        (leg.route_key, leg.route_id, leg.direction, leg.from_stop, leg.to_stop)
        for leg in j.legs
    )


def _states_to_journey(
    states: list[tuple[int, int, int, int]], segments: list[dict[str, Any]]
) -> Journey | None:
    """Convert a (seg_idx, pos, board_pos, transfers_used) chain into a Journey."""
    if not states:
        return None
    legs: list[Leg] = []
    i = 0
    while i < len(states):
        seg_idx, pos, bp, _tu = states[i]
        seq = segments[seg_idx]["stops"]
        j = i
        while j + 1 < len(states):
            sn, pn, bpn, _tn = states[j + 1]
            if sn == seg_idx and bpn == bp:
                j += 1
            else:
                break
        last_pos = states[j][1]
        legs.append(_make_leg(segments[seg_idx], bp, last_pos, seq))
        i = j + 1
    if not legs:
        return None
    ts = legs[0].to_stop if len(legs) > 1 else None
    return Journey(legs=legs, transfer_stop=ts)


def _is_goal_at_stop(
    seq: list[str],
    pos: int,
    board_pos: int,
    D: set[str],
    stop_to_cluster: dict[str, str],
    cluster_members: dict[str, set[str]],
) -> bool:
    if pos <= board_pos:
        return False
    mid = seq[pos]
    return bool(_cluster_set(mid, stop_to_cluster, cluster_members) & D)


def find_journeys(
    db_path: str,
    origin_stop_id: str | list[str],
    dest_stop_id: str | list[str],
    max_transfers: int = 3,
    *,
    transfer_penalty: float = 8.0,
    cost_slack: float = 4.0,
    max_alternatives: int = 80,
) -> list[Journey]:
    """
    Shortest-cost bus paths (Dijkstra on line segments). Cost = bus hops + transfer_penalty per
    interchange. Returns deduplicated journeys within the best cost + cost_slack.
    """
    o_list = (
        [origin_stop_id] if isinstance(origin_stop_id, str) else list(origin_stop_id)
    )
    d_list = [dest_stop_id] if isinstance(dest_stop_id, str) else list(dest_stop_id)
    o_list = [str(x).strip() for x in o_list if x and str(x).strip()]
    d_list = [str(x).strip() for x in d_list if x and str(x).strip()]
    if not o_list or not d_list:
        return []

    stop_to_cluster, cluster_members = load_stop_cluster_maps(db_path)
    O: set[str] = set()
    for o in o_list:
        O |= _cluster_set(o, stop_to_cluster, cluster_members)
    D: set[str] = set()
    for d in d_list:
        D |= _cluster_set(d, stop_to_cluster, cluster_members)
    o_ids = list(O)

    segments = load_route_segments(db_path)
    if not segments:
        return []

    segs_by_stop: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seg_idx_map: dict[tuple[str, int], int] = {}
    for si, seg in enumerate(segments):
        seg_idx_map[(seg["route_key"], int(seg["direction"]))] = si
        for sid in set(seg["stops"]):
            segs_by_stop[sid].append(seg)

    State = tuple[int, int, int, int]  # seg_idx, pos, board_pos, transfers_used
    dist: dict[State, float] = {}
    parent: dict[State, State | None] = {}
    heap: list[tuple[float, int, int, int, int, int]] = []
    tie = 0

    for seg_idx, seg in enumerate(segments):
        seq = seg["stops"]
        i0 = _first_board_index(seq, o_ids)
        if i0 is None:
            continue
        st: State = (seg_idx, i0, i0, 0)
        dist[st] = 0.0
        parent[st] = None
        tie += 1
        heapq.heappush(heap, (0.0, tie, seg_idx, i0, i0, 0))

    if not heap:
        return []

    goal_costs: dict[State, float] = {}

    while heap:
        cost, _, seg_idx, pos, board_pos, transfers_used = heapq.heappop(heap)
        st = (seg_idx, pos, board_pos, transfers_used)
        if cost > dist.get(st, float("inf")):
            continue
        seq = segments[seg_idx]["stops"]

        if _is_goal_at_stop(seq, pos, board_pos, D, stop_to_cluster, cluster_members):
            goal_costs[st] = cost
            continue

        if pos + 1 < len(seq):
            nxt = (seg_idx, pos + 1, board_pos, transfers_used)
            nc = cost + 1.0
            if nc < dist.get(nxt, float("inf")):
                dist[nxt] = nc
                parent[nxt] = st
                tie += 1
                heapq.heappush(
                    heap, (nc, tie, seg_idx, pos + 1, board_pos, transfers_used)
                )

        if pos <= board_pos or transfers_used >= max_transfers:
            continue
        mid = seq[pos]
        mid_c = _cluster_set(mid, stop_to_cluster, cluster_members)
        if mid_c & D:
            continue
        cand: dict[tuple[str, int], dict[str, Any]] = {}
        for sid in mid_c:
            for s in segs_by_stop.get(sid, ()):
                cand[(s["route_key"], int(s["direction"]))] = s
        cur_seg = segments[seg_idx]
        for next_seg in cand.values():
            if _same_segment(next_seg, cur_seg):
                continue
            board_idxs = [
                idx for idx, sid in enumerate(next_seg["stops"]) if sid in mid_c
            ]
            if not board_idxs:
                continue
            j_board = min(board_idxs)
            n2 = seg_idx_map[(next_seg["route_key"], int(next_seg["direction"]))]
            nxt = (n2, j_board, j_board, transfers_used + 1)
            nc = cost + transfer_penalty
            if nc < dist.get(nxt, float("inf")):
                dist[nxt] = nc
                parent[nxt] = st
                tie += 1
                heapq.heappush(
                    heap, (nc, tie, n2, j_board, j_board, transfers_used + 1)
                )

    if not goal_costs:
        return []

    min_c = min(goal_costs.values())
    goal_states = [s for s, c in goal_costs.items() if c <= min_c + cost_slack]
    goal_states.sort(key=lambda s: goal_costs[s])

    seen: set[tuple[tuple[str, str, int, str, str], ...]] = set()
    out: list[Journey] = []

    def backtrack(goal: State) -> list[State]:
        chain: list[State] = []
        cur: State | None = goal
        while cur is not None:
            chain.append(cur)
            cur = parent.get(cur)
        chain.reverse()
        return chain

    for gs in goal_states:
        if len(out) >= max_alternatives:
            break
        chain = backtrack(gs)
        jn = _states_to_journey(chain, segments)
        if jn is None:
            continue
        jn.routing_cost = goal_costs.get(gs, dist.get(gs))
        k = _journey_dedup_key(jn)
        if k in seen:
            continue
        seen.add(k)
        out.append(jn)

    out.sort(key=lambda j: (j.routing_cost or 1e9, journey_bus_hops(j)))
    return out


def load_stop_coords(db_path: str) -> dict[str, tuple[float, float]]:
    """stop_id -> (lat, lng) for stops with coordinates."""
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(
                "SELECT stop_id, lat, lng FROM stops WHERE lat IS NOT NULL AND lng IS NOT NULL"
            )
            rows = cur.fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for sid, la, ln in rows:
        try:
            if la is None or ln is None:
                continue
            la_f, ln_f = float(la), float(ln)
            if la_f == 0 and ln_f == 0:
                continue
            out[str(sid)] = (la_f, ln_f)
        except (TypeError, ValueError):
            continue
    return out


def walk_km_between_stops(
    from_stop_id: str,
    to_stop_id: str,
    coords: dict[str, tuple[float, float]],
) -> float | None:
    """Straight-line km between two stop coordinates; None when coordinates are missing."""
    if from_stop_id == to_stop_id:
        return 0.0
    ca, cb = coords.get(from_stop_id), coords.get(to_stop_id)
    if not ca or not cb:
        return None
    return _haversine_km(ca[0], ca[1], cb[0], cb[1])


def min_walk_km_to_cluster(
    ref_lat: float,
    ref_lng: float,
    stop_id: str,
    *,
    coords: dict[str, tuple[float, float]],
    stop_to_cluster: dict[str, str],
    cluster_members: dict[str, set[str]],
) -> float:
    """Minimum straight-line km from ref point to any stop in the same cluster as stop_id."""
    best = float("inf")
    for sid in _cluster_set(stop_id, stop_to_cluster, cluster_members):
        c = coords.get(sid)
        if not c:
            continue
        la, ln = c
        best = min(best, _haversine_km(ref_lat, ref_lng, la, ln))
    return 0.0 if best == float("inf") else best


def _cluster_min_distance_km(
    lat: float,
    lng: float,
    stop_ids: list[str],
    coords: dict[str, tuple[float, float]],
) -> float | None:
    best = float("inf")
    for sid in stop_ids:
        c = coords.get(sid)
        if not c:
            continue
        best = min(best, _haversine_km(lat, lng, c[0], c[1]))
    return None if best == float("inf") else best


def journey_bus_hops(j: Journey) -> int:
    """Count of bus segments between consecutive stops (proxy for in-vehicle time)."""
    return sum(max(0, len(leg.stops_board_to_alight) - 1) for leg in j.legs)


def load_stop_names_en(db_path: str) -> dict[str, str]:
    """stop_id -> English name (fallback to id)."""
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("SELECT stop_id, stop_name_en FROM stops")
            rows = cur.fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, str] = {}
    for sid, name in rows:
        out[str(sid)] = str(name or sid).strip() or str(sid)
    return out


def load_stop_names_bilingual(db_path: str) -> dict[str, tuple[str, str]]:
    """stop_id -> (name_en, name_tc). TC may be empty."""
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(
                "SELECT stop_id, COALESCE(stop_name_en,''), COALESCE(stop_name_tc,'') FROM stops"
            )
            rows = cur.fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for sid, ne, nt in rows:
        sid = str(sid)
        en = str(ne or sid).strip() or sid
        tc = str(nt or "").strip()
        out[sid] = (en, tc)
    return out


def load_route_terminus_labels(db_path: str) -> dict[str, tuple[str, str]]:
    """route_key -> (origin_en, destination_en) from routes table."""
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(
                "SELECT route_key, COALESCE(origin_en,''), COALESCE(destination_en,'') FROM routes"
            )
            rows = cur.fetchall()
    except sqlite3.Error:
        return {}
    return {str(rk): (str(o or "").strip(), str(d or "").strip()) for rk, o, d in rows}


def load_route_terminus_full(db_path: str) -> dict[str, tuple[str, str, str, str]]:
    """route_key -> (origin_en, destination_en, origin_tc, destination_tc)."""
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("""
                SELECT route_key,
                       COALESCE(origin_en,''), COALESCE(destination_en,''),
                       COALESCE(origin_tc,''), COALESCE(destination_tc,'')
                FROM routes
                """)
            rows = cur.fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, tuple[str, str, str, str]] = {}
    for rk, o_en, d_en, o_tc, d_tc in rows:
        out[str(rk)] = (
            str(o_en or "").strip(),
            str(d_en or "").strip(),
            str(o_tc or "").strip(),
            str(d_tc or "").strip(),
        )
    return out


def route_service_label(origin_en: str, dest_en: str, direction: int) -> str:
    """Registered route direction: dir 1 = origin→dest, dir 2 = return (swap)."""
    o, d = origin_en.strip(), dest_en.strip()
    if not o and not d:
        return ""
    if int(direction) == 2 and o and d:
        return f"{d} → {o}"
    if o and d:
        return f"{o} → {d}"
    return o or d


def route_service_label_pair(
    o_en: str, d_en: str, o_tc: str, d_tc: str, direction: int
) -> tuple[str, str]:
    """(en_line, tc_line) for service headsign; TC line may be empty."""
    en = route_service_label(o_en, d_en, direction)
    tc = route_service_label(o_tc or "", d_tc or "", direction)
    return en, tc


def toward_terminal_bilingual(
    o_en: str, d_en: str, o_tc: str, d_tc: str, direction: int
) -> tuple[str, str]:
    """End-of-line names for 'toward X' in English and Traditional Chinese."""
    en_svc, tc_svc = route_service_label_pair(o_en, d_en, o_tc, d_tc, direction)

    def _one(o: str, d: str, di: int, svc: str) -> str:
        if "→" in svc:
            parts = [p.strip() for p in svc.split("→", 1)]
            if len(parts) > 1 and parts[1]:
                return parts[1]
        o, d = (o or "").strip(), (d or "").strip()
        if int(di) == 2:
            return o or d
        return d or o

    return _one(o_en, d_en, direction, en_svc), _one(
        o_tc or "", d_tc or "", direction, tc_svc
    )


def dedupe_direct_journeys_by_route_and_cluster(
    rows: list[tuple[Journey, float, float, int, int, float, dict[str, Any]]],
    stop_to_cluster: dict[str, str],
) -> list[tuple[Journey, float, float, int, int, float, dict[str, Any]]]:
    """
    Keep one journey per (route_id, board cluster, alight cluster) — same physical trip
    on the same route number, e.g. CTB 671 vs KMB 671 duplicate listings.
    Keeps the lowest ETA among duplicates.
    """
    if not rows:
        return []
    best: dict[tuple[str, str, str], tuple] = {}
    for r in rows:
        j = r[0]
        if len(j.legs) != 1:
            continue
        leg = j.legs[0]
        ck_f = stop_to_cluster.get(leg.from_stop, f"id:{leg.from_stop}")
        ck_t = stop_to_cluster.get(leg.to_stop, f"id:{leg.to_stop}")
        key = (str(leg.route_id), ck_f, ck_t)
        if key not in best or r[5] < best[key][5]:
            best[key] = r
    out = sorted(best.values(), key=lambda x: x[5])
    return out


def leg_path_distance_km(leg: Leg, coords: dict[str, tuple[float, float]]) -> float:
    """Approximate road distance as sum of straight-line gaps between consecutive stops on this leg."""
    seq = leg.stops_board_to_alight
    if len(seq) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(seq, seq[1:]):
        ca, cb = coords.get(a), coords.get(b)
        if not ca or not cb:
            continue
        total += _haversine_km(ca[0], ca[1], cb[0], cb[1])
    return total


def estimate_journey_time_breakdown(
    j: Journey,
    *,
    walk_origin_km: float,
    walk_dest_km: float,
    coords: dict[str, tuple[float, float]],
    avg_bus_speed_kmh: float,
    walking_speed_kmh: float,
    minutes_per_transfer: float,
    fallback_minutes_per_bus_hop: float,
) -> dict[str, Any]:
    """
    Rough ETA: bus time from path distance (or hop count), walking from km, fixed time per interchange.
    """
    per_leg_bus_min: list[float] = []
    bus_total = 0.0
    for leg in j.legs:
        km = leg_path_distance_km(leg, coords)
        hops = max(0, len(leg.stops_board_to_alight) - 1)
        if km > 0.001:
            m = (km / max(avg_bus_speed_kmh, 1.0)) * 60.0
        else:
            m = float(hops) * fallback_minutes_per_bus_hop
        per_leg_bus_min.append(round(m, 1))
        bus_total += m
    walk_km = walk_origin_km + walk_dest_km
    walk_min = (walk_km / max(walking_speed_kmh, 0.1)) * 60.0 if walk_km > 0 else 0.0
    n_xf = len(j.legs) - 1
    xfer_min = float(n_xf) * minutes_per_transfer
    total_min = bus_total + walk_min + xfer_min
    walk_origin_min = (
        (walk_origin_km / max(walking_speed_kmh, 0.1)) * 60.0
        if walk_origin_km > 0
        else 0.0
    )
    walk_dest_min = (
        (walk_dest_km / max(walking_speed_kmh, 0.1)) * 60.0 if walk_dest_km > 0 else 0.0
    )
    return {
        "total_min": round(total_min, 1),
        "bus_min": round(bus_total, 1),
        "walk_min": round(walk_min, 1),
        "walk_origin_min": round(walk_origin_min, 1),
        "walk_dest_min": round(walk_dest_min, 1),
        "transfer_min": round(xfer_min, 1),
        "per_leg_bus_min": per_leg_bus_min,
        "stops_ridden_per_leg": [
            max(0, len(leg.stops_board_to_alight) - 1) for leg in j.legs
        ],
    }


def rank_journeys_for_trip_planner(
    journeys: list[Journey],
    *,
    origin_ref_lat: float | None,
    origin_ref_lng: float | None,
    dest_ref_lat: float | None,
    dest_ref_lng: float | None,
    db_path: str,
    top_n: int = 5,
    max_direct_results: int = 3,
    max_extra_minutes_vs_best: float = 22.0,
    max_ratio_vs_best: float = 1.38,
    avg_bus_speed_kmh: float = 17.0,
    walking_speed_kmh: float = 5.0,
    minutes_per_transfer: float = 4.0,
    fallback_minutes_per_bus_hop: float = 2.4,
) -> tuple[
    list[tuple[Journey, float, float, int, int, float, dict[str, Any]]],
    list[tuple[Journey, float, float, int, int, float, dict[str, Any]]],
]:
    """
    Split into (direct_routes, transfer_routes). Direct = single bus leg, always listed first when present.
    Each group is sorted by ETA and filtered vs the best-in-group (ratio + extra minutes).
    Direct rows are deduped by (route_id, board cluster, alight cluster) so the same trip is not
    listed twice for different operators (e.g. CTB 671 vs KMB 671).
    Direct: up to max_direct_results. Transfer: up to top_n.
    Returns two lists of (journey, wo, wd, hops, n_transfers, eta, breakdown).
    """
    if not journeys:
        return [], []
    coords = load_stop_coords(db_path)
    stop_to_cluster, cluster_members = load_stop_cluster_maps(db_path)
    rows: list[tuple[Journey, float, float, int, int, float, dict[str, Any]]] = []
    for j in journeys:
        hops = journey_bus_hops(j)
        n_xf = len(j.legs) - 1
        wo, wd = 0.0, 0.0
        if (
            origin_ref_lat is not None
            and origin_ref_lng is not None
            and dest_ref_lat is not None
            and dest_ref_lng is not None
            and j.legs
        ):
            wo = min_walk_km_to_cluster(
                origin_ref_lat,
                origin_ref_lng,
                j.legs[0].from_stop,
                coords=coords,
                stop_to_cluster=stop_to_cluster,
                cluster_members=cluster_members,
            )
            wd = min_walk_km_to_cluster(
                dest_ref_lat,
                dest_ref_lng,
                j.legs[-1].to_stop,
                coords=coords,
                stop_to_cluster=stop_to_cluster,
                cluster_members=cluster_members,
            )
        bd = estimate_journey_time_breakdown(
            j,
            walk_origin_km=wo,
            walk_dest_km=wd,
            coords=coords,
            avg_bus_speed_kmh=avg_bus_speed_kmh,
            walking_speed_kmh=walking_speed_kmh,
            minutes_per_transfer=minutes_per_transfer,
            fallback_minutes_per_bus_hop=fallback_minutes_per_bus_hop,
        )
        eta = float(bd["total_min"])
        rows.append((j, wo, wd, hops, n_xf, eta, bd))

    def _filter_eta_window(sub: list) -> list:
        if not sub:
            return []
        sub.sort(key=lambda x: x[5])
        best = sub[0][5]
        cap = min(best * max_ratio_vs_best, best + max_extra_minutes_vs_best)
        return [r for r in sub if r[5] <= cap]

    def _filter_cap(sub: list, cap_n: int) -> list:
        return _filter_eta_window(sub)[:cap_n]

    direct_in = [r for r in rows if len(r[0].legs) == 1]
    xfer_in = [r for r in rows if len(r[0].legs) > 1]
    # Same physical trip (route_id + board/alight clusters) can appear twice (e.g. CTB 671 vs KMB 671).
    direct_out = dedupe_direct_journeys_by_route_and_cluster(
        _filter_eta_window(direct_in), stop_to_cluster
    )[:max_direct_results]
    xfer_out = _filter_cap(xfer_in, top_n)
    return direct_out, xfer_out


def load_stop_clusters_for_ui(db_path: str, precision: int = 4) -> list[dict[str, Any]]:
    """
    Rows for trip-planner dropdowns: merged stops at ~same coordinates.
    Each row: cluster_key, label_en, stop_ids (list), lat, lng, companies (short string).
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("""
                SELECT stop_id, stop_name_en, COALESCE(stop_name_tc,''), COALESCE(company,''), lat, lng
                FROM stops
                ORDER BY stop_name_en, stop_id
                """)
            rows = cur.fetchall()
    except sqlite3.Error:
        return []

    buckets: dict[str, list[tuple[str, str, str, str, float, float]]] = defaultdict(
        list
    )
    for sid, ne, tc, co, la, ln in rows:
        try:
            lat, lng = float(la), float(ln)
        except (TypeError, ValueError):
            lat, lng = 0.0, 0.0
        if lat == 0 and lng == 0:
            ck = f"id:{sid}"
        else:
            ck = f"{round(lat, precision):.{precision}f},{round(lng, precision):.{precision}f}"
        buckets[ck].append(
            (str(sid), str(ne or ""), str(tc or ""), str(co or ""), lat, lng)
        )

    out: list[dict[str, Any]] = []
    for ck, items in buckets.items():
        ids = [x[0] for x in items]
        names = [x[1] for x in items if x[1]]
        name0 = names[0] if names else ids[0]
        cos = sorted({x[3] for x in items if x[3]})
        lat_m = sum(x[4] for x in items) / len(items)
        lng_m = sum(x[5] for x in items) / len(items)
        n_var = len(ids)
        co_hint = cos[0] if len(cos) == 1 else f"{len(cos)} operators"
        label = name0
        if n_var > 1:
            label = f"{name0} · {n_var} stop IDs ({co_hint})"
        out.append(
            {
                "cluster_key": ck,
                "label": label,
                "name_primary": name0,
                "stop_ids": ids,
                "lat": lat_m,
                "lng": lng_m,
                "companies": cos,
            }
        )
    out.sort(key=lambda r: (r["name_primary"].lower(), r["cluster_key"]))
    return out


def nearest_clusters(
    db_path: str, lat: float, lng: float, k: int = 15, precision: int = 4
) -> list[tuple[list[str], str, float]]:
    """Return up to k clusters sorted by the nearest stop in each cluster."""
    clusters = load_stop_clusters_for_ui(db_path, precision=precision)
    coords = load_stop_coords(db_path)
    scored: list[tuple[float, list[str], str]] = []
    for c in clusters:
        dist = _cluster_min_distance_km(lat, lng, list(c["stop_ids"]), coords)
        if dist is None:
            continue
        scored.append((dist, c["stop_ids"], c["label"]))
    scored.sort(key=lambda x: x[0])
    return [(ids, lab, d) for d, ids, lab in scored[:k]]


def walk_radius_km(walk_minutes: float = 15.0, walking_speed_kmh: float = 5.0) -> float:
    """Straight-line radius matching a walk time at given speed (default ~15 min @ 5 km/h ≈ 1.25 km)."""
    return max(0.05, (walk_minutes / 60.0) * walking_speed_kmh)


def clusters_within_walk_radius(
    db_path: str,
    lat: float,
    lng: float,
    *,
    walk_minutes: float = 15.0,
    walking_speed_kmh: float = 5.0,
    precision: int = 4,
) -> list[tuple[list[str], str, float]]:
    """
    All merged stop clusters whose nearest member stop lies within straight-line distance of walk_radius_km.
    Sorted by distance to (lat, lng). Empty if no coordinates in DB near the point.
    """
    rkm = walk_radius_km(walk_minutes, walking_speed_kmh)
    clusters = load_stop_clusters_for_ui(db_path, precision=precision)
    coords = load_stop_coords(db_path)
    scored: list[tuple[float, list[str], str]] = []
    for c in clusters:
        dist = _cluster_min_distance_km(lat, lng, list(c["stop_ids"]), coords)
        if dist is None:
            continue
        if dist <= rkm:
            scored.append((dist, c["stop_ids"], c["label"]))
    scored.sort(key=lambda x: x[0])
    return [(ids, lab, d) for d, ids, lab in scored]


def catchment_stop_ids_ordered(
    clusters_in_radius: list[tuple[list[str], str, float]],
    max_stop_ids: int | None = None,
) -> list[str]:
    """
    Flatten cluster stop IDs in distance order (clusters already sorted by distance).
    Optionally cap how many distinct stop IDs we keep (closest clusters first).
    """
    out: list[str] = []
    seen: set[str] = set()
    for ids, _, _ in clusters_in_radius:
        for sid in ids:
            if sid in seen:
                continue
            seen.add(sid)
            out.append(sid)
            if max_stop_ids is not None and len(out) >= max_stop_ids:
                return out
    return out


def nearest_stops(
    db_path: str, lat: float, lng: float, k: int = 12
) -> list[tuple[str, str, float]]:
    """Return up to k nearest raw stops (stop_id, name_en, distance_km) — legacy helper."""
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(
                "SELECT stop_id, stop_name_en, lat, lng FROM stops WHERE lat IS NOT NULL AND lng IS NOT NULL "
                "AND lat BETWEEN 22.0 AND 22.7 AND lng BETWEEN 113.7 AND 114.5"
            )
            rows = cur.fetchall()
    except sqlite3.Error:
        return []
    scored: list[tuple[float, str, str, float, float]] = []
    for sid, name, la, ln in rows:
        try:
            la, ln = float(la), float(ln)
        except (TypeError, ValueError):
            continue
        if la == 0 and ln == 0:
            continue
        dist = _haversine_km(lat, lng, la, ln)
        scored.append((dist, str(sid), str(name or sid), la, ln))
    scored.sort(key=lambda x: x[0])
    out: list[tuple[str, str, float]] = []
    for dist, sid, name, _, _ in scored[:k]:
        out.append((sid, name, dist))
    return out
