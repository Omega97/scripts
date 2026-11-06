"""Graph-level operations: graph building, pathfinding, stats and repair."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple

from .models import Connection, Person


def build_edges(persons: Dict[str, Person]) -> List[Tuple[str, str, Connection]]:
    """Return undirected edges, deduplicating the bidirectional storage.

    Connections are stored on both endpoints; each distinct pair is returned
    once, carrying the connection data found on the lower-id endpoint.
    """
    seen: Set[Tuple[str, str]] = set()
    edges: List[Tuple[str, str, Connection]] = []
    for person_id, person in persons.items():
        for conn in person.connections:
            a, b = sorted((person_id, conn.target_id))
            key = (a, b)
            if key in seen:
                continue
            seen.add(key)
            edges.append((a, b, conn))
    return edges


def adjacency(persons: Dict[str, Person]) -> Dict[str, List[str]]:
    """Build an undirected adjacency list from stored connections."""
    adj: Dict[str, List[str]] = defaultdict(list)
    for person_id, person in persons.items():
        for conn in person.connections:
            if conn.target_id in persons:
                adj[person_id].append(conn.target_id)
    return dict(adj)


def shortest_path(
    persons: Dict[str, Person], start: str, goal: str
) -> Optional[List[str]]:
    """Breadth-first search between two nodes. Returns node ids or None."""
    if start == goal:
        return [start]
    adj = adjacency(persons)
    if start not in adj or goal not in adj:
        return None
    prev: Dict[str, Optional[str]] = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        for nxt in adj.get(current, []):
            if nxt not in prev:
                prev[nxt] = current
                queue.append(nxt)
    if goal not in prev:
        return None
    path: List[str] = []
    node: Optional[str] = goal
    while node is not None:
        path.append(node)
        node = prev[node]
    path.reverse()
    return path


def connected_components(persons: Dict[str, Person]) -> List[Set[str]]:
    adj = adjacency(persons)
    seen: Set[str] = set()
    components: List[Set[str]] = []
    for node in adj:
        if node in seen:
            continue
        comp: Set[str] = set()
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            seen.add(cur)
            stack.extend(adj.get(cur, []))
        components.append(comp)
    for node in persons:
        if node not in seen:  # isolated node with no connections
            components.append({node})
            seen.add(node)
    return components


def compute_stats(persons: Dict[str, Person]) -> dict:
    edges = build_edges(persons)
    degrees: Dict[str, int] = defaultdict(int)
    for a, b, _ in edges:
        degrees[a] += 1
        degrees[b] += 1
    for pid in persons:
        degrees.setdefault(pid, 0)

    type_dist: Dict[str, int] = defaultdict(int)
    for _, _, conn in edges:
        type_dist[conn.type] += 1

    most_connected = sorted(
        degrees.items(), key=lambda kv: (-kv[1], kv[0])
    )[:10]

    return {
        "total_nodes": len(persons),
        "total_edges": len(edges),
        "degrees": dict(degrees),
        "most_connected": most_connected,
        "type_distribution": dict(type_dist),
    }


def find_orphans(persons: Dict[str, Person]) -> List[Tuple[str, str]]:
    """Find connections that point to a non-existent person id.

    Returns a list of ``(person_id, target_id)`` tuples.
    """
    orphans: List[Tuple[str, str]] = []
    for person_id, person in persons.items():
        for conn in person.connections:
            if conn.target_id not in persons:
                orphans.append((person_id, conn.target_id))
    return orphans


def repair(persons: Dict[str, Person]) -> Tuple[int, int]:
    """Remove orphaned connections in place.

    Returns ``(removed_connections, affected_persons)``.
    """
    removed = 0
    affected = 0
    for person in persons.values():
        before = len(person.connections)
        person.connections = [
            c for c in person.connections if c.target_id in persons
        ]
        removed += before - len(person.connections)
        if len(person.connections) != before:
            affected += 1
    return removed, affected
