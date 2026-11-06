"""3D visualization renderer.

Builds a graph payload from Person records, computes a 3D force-directed
layout, injects the data into the Three.js HTML template, and opens it in the
default browser.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path
from typing import Dict, Optional

from ..core.graph_logic import build_edges
from ..core.models import Person
from .layout import compute_layout

TEMPLATE_PATH = Path(__file__).parent / "assets" / "template.html"

DEFAULT_STATUS_COLORS = {
    "active": "#4caf50",
    "inactive": "#9e9e9e",
    "archived": "#f44336",
}


def status_colors(config: dict) -> Dict[str, str]:
    return config.get("viz", {}).get("colors", DEFAULT_STATUS_COLORS)


def build_graph_data(
    persons: Dict[str, Person],
    config: dict,
    filter_type: Optional[str] = None,
) -> dict:
    """Convert persons into ``{nodes, links}`` for the 3D engine."""
    edges = build_edges(persons)
    if filter_type:
        edges = [e for e in edges if e[2].type == filter_type]

    # Determine which nodes actually appear in the filtered subgraph.
    endpoints: set = set()
    for a, b, _ in edges:
        endpoints.add(a)
        endpoints.add(b)

    nodes = []
    for pid in sorted(persons):
        if filter_type and pid not in endpoints:
            continue
        person = persons[pid]
        nodes.append(
            {
                "id": pid,
                "name": person.name,
                "status": person.current_status,
                "description": person.description,
                "degree": 0,
            }
        )

    degree: Dict[str, int] = {n["id"]: 0 for n in nodes}
    for a, b, _ in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    for n in nodes:
        n["degree"] = degree[n["id"]]

    links = [
        {
            "source": a,
            "target": b,
            "type": conn.type,
            "strength": conn.strength,
        }
        for a, b, conn in edges
    ]

    # Seed positions with a Python-side force-directed layout (warm start).
    node_ids = [n["id"] for n in nodes]
    positions = compute_layout(
        node_ids, [(l["source"], l["target"]) for l in links], config
    )
    for n in nodes:
        x, y, z = positions[n["id"]]
        n["x"], n["y"], n["z"] = x, y, z

    return {"nodes": nodes, "links": links}


def render_html(graph_data: dict, config: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_json = json.dumps(graph_data)
    colors_json = json.dumps(status_colors(config))
    return (
        template.replace("__GRAPH_DATA__", data_json)
        .replace("__STATUS_COLORS__", colors_json)
    )


def write_html(graph_data: dict, config: dict, directory: Optional[Path] = None) -> Path:
    html = render_html(graph_data, config)
    if directory is not None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "nodenet_graph.html"
        path.write_text(html, encoding="utf-8")
    else:
        fd, tmp = tempfile.mkstemp(suffix=".html", prefix="nodenet_")
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write(html)
        path = Path(tmp)
    return path


def _browser_exe_candidates(browser: str) -> list:
    """Return candidate executable names/paths for a browser name."""
    name = browser.strip()
    if name.lower() in ("firefox", "firefox.exe"):
        cands = []
        if os.name == "nt":
            for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(env)
                if base:
                    cands.append(os.path.join(base, "Mozilla Firefox", "firefox.exe"))
        cands += ["firefox", "firefox.exe"]
        return cands
    return [name]


def _find_browser_exe(browser: str) -> Optional[str]:
    for cand in _browser_exe_candidates(browser):
        if os.path.sep in cand or (os.path.altsep and os.path.altsep in cand):
            if os.path.isfile(cand):
                return cand
        else:
            found = shutil.which(cand)
            if found:
                return found
    return None


def open_in_browser(path: Path, browser: Optional[str] = None) -> bool:
    """Open ``path`` in a browser.

    If ``browser`` is given (e.g. ``"firefox"``), try to locate and launch it
    directly; otherwise fall back to the system default browser.
    """
    uri = path.as_uri()
    if browser:
        exe = _find_browser_exe(browser)
        if exe:
            try:
                subprocess.Popen([exe, uri])
                return True
            except OSError:
                pass
        try:
            return webbrowser.get(browser).open(uri)
        except webbrowser.Error:
            pass
    return webbrowser.open(uri)


def visualize(
    persons: Dict[str, Person],
    config: dict,
    filter_type: Optional[str] = None,
    open_browser: bool = True,
    output_dir: Optional[Path] = None,
    browser: Optional[str] = None,
) -> Path:
    graph_data = build_graph_data(persons, config, filter_type)
    path = write_html(graph_data, config, directory=output_dir)
    if open_browser:
        open_in_browser(path, browser)
    return path
