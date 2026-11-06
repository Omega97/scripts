"""3D force-directed graph layout.

A dependency-free implementation of Fruchterman-Reingold in three dimensions,
used to seed node positions before the browser runs its own force simulation.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Sequence, Tuple

NodeId = str
Edge = Tuple[NodeId, NodeId]
Point = Tuple[float, float, float]


def _random_unit(rng: random.Random) -> Point:
    """Random point on the surface of a unit sphere."""
    theta = rng.uniform(0, 2 * math.pi)
    phi = math.acos(rng.uniform(-1, 1))
    return (
        math.sin(phi) * math.cos(theta),
        math.sin(phi) * math.sin(theta),
        math.cos(phi),
    )


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Point, s: float) -> Point:
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm(a: Point) -> float:
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def fruchterman_reingold_3d(
    nodes: Sequence[NodeId],
    edges: Sequence[Edge],
    iterations: int = 300,
    repulsion: float = 1.0,
    attraction: float = 0.1,
    gravity: float = 0.01,
    width: float = 10.0,
    seed: int = 42,
) -> Dict[NodeId, Point]:
    """Compute a 3D force-directed layout.

    Args:
        nodes: Unique node ids.
        edges: Undirected edge pairs of node ids.
        iterations: Number of simulation steps.
        repulsion: Repulsive force constant between all node pairs.
        attraction: Attractive spring constant along edges.
        gravity: Pull toward the origin, keeping the graph centred.
        width: Target bounding-box size (normalised roughly to this scale).
        seed: RNG seed for deterministic output.
    """
    rng = random.Random(seed)
    node_set = set(nodes)

    # Initial positions scattered near the origin.
    positions: Dict[NodeId, Point] = {
        n: _scale(_random_unit(rng), rng.uniform(0.1, 1.0)) for n in nodes
    }

    area = max(width ** 3, 1.0)
    k = (area / max(len(node_set), 1)) ** (1.0 / 3.0)

    adj: Dict[NodeId, List[NodeId]] = {n: [] for n in node_set}
    for a, b in edges:
        if a in node_set and b in node_set and b not in adj[a]:
            adj[a].append(b)
            adj[b].append(a)

    def cool(t: int) -> float:
        return max(0.0, 1.0 - t / iterations)

    temperature = width / 10.0

    for it in range(iterations):
        displacements: Dict[NodeId, Point] = {n: (0.0, 0.0, 0.0) for n in node_set}

        # Repulsive forces between every pair of nodes (O(n^2), fine for
        # personal networks).
        ns = list(node_set)
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                a, b = ns[i], ns[j]
                delta = _sub(positions[a], positions[b])
                dist = _norm(delta) or 0.01
                force = (k ** 2) / dist * repulsion
                unit = _scale(delta, 1.0 / dist)
                disp = _scale(unit, force)
                displacements[a] = _add(displacements[a], disp)
                displacements[b] = _sub(displacements[b], disp)

        # Attractive forces along edges.
        for a, b in edges:
            if a not in node_set or b not in node_set:
                continue
            delta = _sub(positions[a], positions[b])
            dist = _norm(delta) or 0.01
            force = (dist ** 2) / k * attraction
            unit = _scale(delta, 1.0 / dist)
            disp = _scale(unit, force)
            displacements[a] = _sub(displacements[a], disp)
            displacements[b] = _add(displacements[b], disp)

        # Apply displacement, capped by temperature, plus gravity to centre.
        for n in node_set:
            disp = displacements[n]
            dlen = _norm(disp)
            if dlen > 0:
                cap = min(dlen, temperature)
                disp = _scale(disp, cap / dlen)
            gravity_disp = _scale(positions[n], -gravity)
            positions[n] = _add(_add(positions[n], disp), gravity_disp)

        temperature = cool(it) * (width / 10.0)

    # Centre the layout on the origin and normalise roughly to `width`.
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    zs = [p[2] for p in positions.values()]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    cz = sum(zs) / len(zs)
    max_r = max(
        math.sqrt((p[0] - cx) ** 2 + (p[1] - cy) ** 2 + (p[2] - cz) ** 2)
        for p in positions.values()
    ) or 1.0
    scale = (width / 2.0) / max_r

    return {
        n: ((p[0] - cx) * scale, (p[1] - cy) * scale, (p[2] - cz) * scale)
        for n, p in positions.items()
    }


def compute_layout(
    nodes: Sequence[NodeId],
    edges: Sequence[Edge],
    config: dict,
) -> Dict[NodeId, Point]:
    """Convenience wrapper that reads parameters from the app config."""
    params = config.get("layout", {})
    return fruchterman_reingold_3d(
        nodes,
        edges,
        iterations=int(params.get("iterations", 300)),
        repulsion=float(params.get("repulsion", 1.0)),
        attraction=float(params.get("attraction", 0.1)),
        gravity=float(params.get("gravity", 0.01)),
    )
