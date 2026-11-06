"""NodeNet CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from ..core.storage import Storage
from . import ui_helpers as ui
from . import commands

PROJECT_ROOT = Path(__file__).resolve().parents[2]

app = typer.Typer(
    name="nodenet",
    help="NodeNet — a personal network manager stored as JSON files, with 3D graph visualization.",
    add_completion=False,
    no_args_is_help=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    data_dir: Path = typer.Option(
        PROJECT_ROOT / "data",
        "--data-dir",
        help="Directory that contains the 'persons/' subfolder.",
    ),
    config_path: Path = typer.Option(
        PROJECT_ROOT / "config.json",
        "--config",
        help="Path to the app config.json.",
    ),
) -> None:
    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            ui.error(f"Invalid config file '{config_path}': {exc}")
            raise typer.Exit(1)
    else:
        ui.warn(f"Config file '{config_path}' not found; using defaults.")

    storage = Storage(data_dir / "persons")
    ctx.obj = commands.AppContext(storage=storage, config=config, data_dir=data_dir)


# A. Node (Person) management
app.command("add", help="Interactively create a new person.")(commands.cmd_add)
app.command("edit", help="Modify an existing person (by id or name).")(commands.cmd_edit)
app.command("delete", help="Remove a person and clean up their connections.")(commands.cmd_delete)
app.command("view", help="Display a formatted summary of a person.")(commands.cmd_view)
app.command("list", help="Paginated table of all people.")(commands.cmd_list)

# B. Connection (Edge) management
app.command("connect", help="Link two people together.")(commands.cmd_connect)
app.command("disconnect", help="Remove a link between two people.")(commands.cmd_disconnect)
app.command("update-link", help="Change the type/notes of an existing connection.")(commands.cmd_update_link)

# C. Search & analytics
app.command("search", help="Full-text search across names, descriptions and info.")(commands.cmd_search)
app.command("find-path", help="Shortest path between two people (Six Degrees).")(commands.cmd_find_path)
app.command("stats", help="Show network statistics.")(commands.cmd_stats)

# D. Visualization
app.command("visualize", help="Generate and open the 3D network in your browser.")(commands.cmd_visualize)
app.command("viz-filter", help="Visualize only a specific connection type.")(commands.cmd_viz_filter)

# E. Repair
app.command("repair", help="Clean up orphaned connections.")(commands.cmd_repair)

# F. Export
app.command("export", help="Export everyone to Obsidian-friendly Markdown.")(commands.cmd_export)


if __name__ == "__main__":
    app()
