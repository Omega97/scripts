"""Command implementations for the NodeNet CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import typer
from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from ..core import exporter
from ..core import graph_logic
from ..core.models import Connection, Information, Person
from ..core.storage import Storage
from ..viz import renderer
from . import ui_helpers as ui


@dataclass
class AppContext:
    storage: Storage
    config: dict
    data_dir: Path


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def load_persons(ctx: typer.Context) -> Dict[str, Person]:
    persons, errors = ctx.obj.storage.load_all()
    for err in errors:
        ui.warn(f"Could not read person file: {err}")
    return persons


def resolve_id(ctx: typer.Context, fragment: str, persons: Optional[Dict[str, Person]] = None) -> str:
    if persons is None:
        persons = load_persons(ctx)

    if fragment in persons:
        return fragment

    prefix_matches = [pid for pid in persons if pid.startswith(fragment)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        ui.error(f"Ambiguous id prefix '{fragment}'. Matching ids:")
        for m in prefix_matches:
            ui.console.print(f"  {m}  {persons[m].name}")
        raise typer.Exit(1)

    name_matches = [p.id for p in persons.values() if fragment.lower() in p.name.lower()]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        ui.error(f"Multiple people match '{fragment}':")
        for m in name_matches:
            ui.console.print(f"  {persons[m].name}  ({m})")
        raise typer.Exit(1)

    ui.error(f"No person matches '{fragment}'.")
    raise typer.Exit(1)


def save_many(ctx: typer.Context, people: List[Person]) -> None:
    for person in people:
        ctx.obj.storage.save(person)


# --------------------------------------------------------------------------
# A. Node (Person) management
# --------------------------------------------------------------------------
def cmd_add(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Person's name (skips prompt)."),
) -> None:
    cfg = ctx.obj.config
    ui.console.print(Panel("Add a new person", border_style="cyan", box=box.ROUNDED))
    if not name:
        name = ui.prompt_text("Name", allow_empty=False)
        if not name:
            ui.error("Name is required.")
            raise typer.Exit(1)

    description = ui.prompt_text("Description") or ""
    status = ui.prompt_choice(
        "Status",
        choices=["active", "inactive", "archived"],
        default=cfg.get("default_status", "active"),
    )
    email = ui.prompt_text("Email") or ""
    phone = ui.prompt_text("Phone") or ""
    gender = ui.prompt_text("Gender") or ""
    locations_raw = ui.prompt_text("Locations (comma-separated)") or ""
    linkedin = ui.prompt_text("LinkedIn") or ""
    tags_raw = ui.prompt_text("Tags (comma-separated)") or ""

    locations = [s.strip() for s in locations_raw.split(",") if s.strip()]
    tags = [s.strip() for s in tags_raw.split(",") if s.strip()]

    person = Person.create(
        name=name.strip(),
        description=description.strip(),
        current_status=status,  # type: ignore[arg-type]
        information=Information(
            email=email.strip() or None,
            phone=phone.strip() or None,
            gender=gender.strip() or None,
            locations=locations,
            linkedin=linkedin.strip() or None,
            tags=tags,
        ),
    )
    ctx.obj.storage.save(person)
    ui.success(f"Added '{person.name}' with id {person.id}")


def cmd_view(ctx: typer.Context, person_ref: str) -> None:
    persons = load_persons(ctx)
    pid = resolve_id(ctx, person_ref, persons)
    person = persons[pid]
    names = {p.id: p.name for p in persons.values()}
    ui.print_person(person, names)


def cmd_edit(ctx: typer.Context, person_ref: str) -> None:
    persons = load_persons(ctx)
    pid = resolve_id(ctx, person_ref, persons)
    person = persons[pid]
    ui.console.print(f"Editing [bold]{person.name}[/bold]. Press Enter to keep the current value.")

    name = ui.prompt_text("Name", default=person.name) or person.name
    description = ui.prompt_text("Description", default=person.description) or person.description
    status = ui.prompt_choice(
        "Status", choices=["active", "inactive", "archived"], default=person.current_status
    )

    info = person.information
    email = ui.prompt_text("Email", default=info.email or "") or info.email
    phone = ui.prompt_text("Phone", default=info.phone or "") or info.phone
    gender = ui.prompt_text("Gender", default=info.gender or "") or info.gender

    locations_default = ", ".join(info.locations)
    locations_raw = ui.prompt_text("Locations (comma-separated)", default=locations_default)
    locations = [s.strip() for s in (locations_raw or "").split(",") if s.strip()]

    linkedin = ui.prompt_text("LinkedIn", default=info.linkedin or "") or info.linkedin
    tags_default = ", ".join(info.tags)
    tags_raw = ui.prompt_text("Tags (comma-separated)", default=tags_default)
    tags = [s.strip() for s in (tags_raw or "").split(",") if s.strip()]

    person.name = name.strip()
    person.description = description.strip()
    person.current_status = status  # type: ignore[assignment]
    person.information = Information(
        email=(email.strip() if isinstance(email, str) else None),
        phone=(phone.strip() if isinstance(phone, str) else None),
        gender=(gender.strip() if isinstance(gender, str) else None),
        locations=locations,
        linkedin=(linkedin.strip() if isinstance(linkedin, str) else None),
        tags=tags,
    )
    person.touch()
    ctx.obj.storage.save(person)
    ui.success(f"Updated '{person.name}'.")


def cmd_delete(ctx: typer.Context, person_ref: str, force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation.")) -> None:
    persons = load_persons(ctx)
    pid = resolve_id(ctx, person_ref, persons)
    person = persons[pid]

    if not force and not ui.confirm(f"Delete '{person.name}' and all connections to them?", default=False):
        ui.warn("Aborted.")
        return

    ctx.obj.storage.delete(pid)

    # Clean up this person's connections in every other file.
    changed: List[Person] = []
    for other in persons.values():
        if other.id == pid:
            continue
        if other.remove_connection(pid):
            changed.append(other)
    save_many(ctx, changed)

    ui.success(
        f"Deleted '{person.name}' and removed {len(changed)} outgoing references."
    )


def cmd_list(
    ctx: typer.Context,
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status."),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag."),
    page_size: int = typer.Option(10, "--page-size", help="Rows per page."),
    all_rows: bool = typer.Option(False, "--all", "-a", help="Show all rows at once."),
) -> None:
    persons = load_persons(ctx)
    people = list(persons.values())

    if status:
        people = [p for p in people if p.current_status == status]
    if tag:
        people = [p for p in people if tag.lower() in {t.lower() for t in p.information.tags}]

    if not people:
        ui.warn("No people match the given filters.")
        return

    people.sort(key=lambda p: p.name.lower())

    if all_rows:
        ui.console.print(ui.build_person_table(people))
        ui.console.print(f"[dim]{len(people)} people[/dim]")
        return

    pages = [people[i : i + page_size] for i in range(0, len(people), page_size)]
    current = 0
    while True:
        ui.console.print(ui.build_person_table(pages[current]))
        ui.console.print(
            f"[dim]Page {current + 1}/{len(pages)} · {len(people)} people[/dim]"
        )
        if len(pages) == 1:
            break
        action = ui.prompt_text("Next (n), previous (p), or quit (q)", default="n")
        if action in ("q", "quit"):
            break
        if action in ("p", "prev", "previous"):
            current = (current - 1) % len(pages)
        else:
            current = (current + 1) % len(pages)


# --------------------------------------------------------------------------
# B. Connection (Edge) management
# --------------------------------------------------------------------------
def cmd_connect(
    ctx: typer.Context,
    person1: str,
    person2: str,
    type_: Optional[str] = typer.Option(None, "--type", "-t", help="Connection type."),
    strength: Optional[str] = typer.Option(None, "--strength", "-s", help="Connection strength."),
    notes: Optional[str] = typer.Option(None, "--notes", help="Notes about the connection."),
) -> None:
    persons = load_persons(ctx)
    id1 = resolve_id(ctx, person1, persons)
    id2 = resolve_id(ctx, person2, persons)
    if id1 == id2:
        ui.error("Cannot connect a person to themselves.")
        raise typer.Exit(1)

    a, b = persons[id1], persons[id2]
    cfg = ctx.obj.config

    if a.has_connection(id2) or b.has_connection(id1):
        ui.error(f"'{a.name}' and '{b.name}' are already connected.")
        raise typer.Exit(1)

    if type_ is None:
        type_ = ui.prompt_choice(
            "Connection type",
            choices=cfg.get("connection_types", ["friend", "coworker", "other"]),
            default="friend",
        )
    if strength is None:
        strength = ui.prompt_choice(
            "Strength", choices=["weak", "medium", "strong"], default="medium"
        )
    if notes is None:
        notes = ui.prompt_text("Notes") or ""

    conn_ab = Connection(target_id=id2, type=type_, strength=strength, notes=notes)  # type: ignore[arg-type]
    conn_ba = Connection(target_id=id1, type=type_, strength=strength, notes=notes)  # type: ignore[arg-type]

    a.add_connection(conn_ab)
    b.add_connection(conn_ba)
    save_many(ctx, [a, b])
    ui.success(f"Connected '{a.name}' and '{b.name}' ({type_}, {strength}).")


def cmd_disconnect(ctx: typer.Context, person1: str, person2: str) -> None:
    persons = load_persons(ctx)
    id1 = resolve_id(ctx, person1, persons)
    id2 = resolve_id(ctx, person2, persons)
    a, b = persons[id1], persons[id2]

    removed_a = a.remove_connection(id2)
    removed_b = b.remove_connection(id1)
    if not removed_a and not removed_b:
        ui.warn(f"'{a.name}' and '{b.name}' are not connected.")
        return

    save_many(ctx, [a, b])
    ui.success(f"Disconnected '{a.name}' and '{b.name}'.")


def cmd_update_link(
    ctx: typer.Context,
    person1: str,
    person2: str,
    type_: Optional[str] = typer.Option(None, "--type", "-t", help="New connection type."),
    strength: Optional[str] = typer.Option(None, "--strength", "-s", help="New strength."),
    notes: Optional[str] = typer.Option(None, "--notes", help="New notes."),
) -> None:
    persons = load_persons(ctx)
    id1 = resolve_id(ctx, person1, persons)
    id2 = resolve_id(ctx, person2, persons)
    a, b = persons[id1], persons[id2]

    conn_a = a.get_connection(id2)
    conn_b = b.get_connection(id1)
    if conn_a is None or conn_b is None:
        ui.error(f"'{a.name}' and '{b.name}' are not connected.")
        raise typer.Exit(1)

    if type_ is None:
        type_ = ui.prompt_text("Type", default=conn_a.type) or conn_a.type
    if strength is None:
        strength = ui.prompt_choice("Strength", choices=["weak", "medium", "strong"], default=conn_a.strength)
    if notes is None:
        notes = ui.prompt_text("Notes", default=conn_a.notes) or conn_a.notes

    conn_a.type = type_
    conn_a.strength = strength  # type: ignore[assignment]
    conn_a.notes = notes
    conn_b.type = type_
    conn_b.strength = strength  # type: ignore[assignment]
    conn_b.notes = notes

    a.touch()
    b.touch()
    save_many(ctx, [a, b])
    ui.success(f"Updated connection between '{a.name}' and '{b.name}'.")


# --------------------------------------------------------------------------
# C. Search & analytics
# --------------------------------------------------------------------------
def _searchable_text(person: Person) -> str:
    parts = [
        person.name,
        person.description,
        person.current_status,
        person.information.email or "",
        person.information.phone or "",
        person.information.linkedin or "",
        " ".join(person.information.locations),
        " ".join(person.information.tags),
    ]
    for conn in person.connections:
        parts.append(conn.type)
        parts.append(conn.notes)
    return " ".join(parts).lower()


def cmd_search(ctx: typer.Context, query: str) -> None:
    persons = load_persons(ctx)
    q = query.lower()
    matches = [p for p in persons.values() if q in _searchable_text(p)]
    if not matches:
        ui.warn(f"No results for '{query}'.")
        return
    matches.sort(key=lambda p: p.name.lower())
    ui.console.print(ui.build_person_table(matches))
    ui.console.print(f"[dim]{len(matches)} result(s)[/dim]")


def cmd_find_path(ctx: typer.Context, person1: str, person2: str) -> None:
    persons = load_persons(ctx)
    id1 = resolve_id(ctx, person1, persons)
    id2 = resolve_id(ctx, person2, persons)

    path = graph_logic.shortest_path(persons, id1, id2)
    if path is None:
        ui.error(f"No connection path between '{persons[id1].name}' and '{persons[id2].name}'.")
        raise typer.Exit(1)

    ui.console.print(
        f"[bold]Shortest path[/bold] ({len(path) - 1} degree(s)) between "
        f"'[cyan]{escape(persons[id1].name)}[/cyan]' and '[cyan]{escape(persons[id2].name)}[/cyan]':"
    )
    for i in range(len(path) - 1):
        cur = persons[path[i]]
        nxt = persons[path[i + 1]]
        conn = cur.get_connection(nxt.id)
        edge_label = f" — {escape(conn.type)}" if conn else ""
        ui.console.print(
            f"  {i + 1}. [bold]{escape(cur.name)}[/bold]{edge_label} → [bold]{escape(nxt.name)}[/bold]"
        )
        if conn and conn.notes:
            ui.console.print(f"      [dim]{escape(conn.notes)}[/dim]")


def cmd_stats(ctx: typer.Context) -> None:
    persons = load_persons(ctx)
    stats = graph_logic.compute_stats(persons)

    table = Table(title="Network Statistics", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Total nodes (people)", str(stats["total_nodes"]))
    table.add_row("Total edges (connections)", str(stats["total_edges"]))
    ui.console.print(table)

    if stats["most_connected"]:
        top = Table(title="Most Connected", box=box.SIMPLE_HEAVY, header_style="bold cyan")
        top.add_column("Rank", justify="right", style="dim")
        top.add_column("Name", style="bold")
        top.add_column("Connections", justify="right")
        for rank, (pid, deg) in enumerate(stats["most_connected"], start=1):
            top.add_row(str(rank), persons[pid].name, str(deg))
        ui.console.print(top)

    if stats["type_distribution"]:
        dist = Table(title="Connection Types", box=box.SIMPLE_HEAVY, header_style="bold cyan")
        dist.add_column("Type", style="bold")
        dist.add_column("Count", justify="right")
        for t, count in sorted(stats["type_distribution"].items(), key=lambda kv: -kv[1]):
            dist.add_row(t, str(count))
        ui.console.print(dist)


# --------------------------------------------------------------------------
# D. Visualization
# --------------------------------------------------------------------------
def cmd_visualize(
    ctx: typer.Context,
    browser: Optional[str] = typer.Option(
        None, "--browser", "-b",
        help="Browser to open (e.g. firefox, chrome). Defaults to config viz.browser, then the system default.",
    ),
) -> None:
    persons = load_persons(ctx)
    if not persons:
        ui.warn("No people to visualize. Add some first.")
        return
    browser = browser or ctx.obj.config.get("viz", {}).get("browser")
    path = renderer.visualize(persons, ctx.obj.config, open_browser=True, browser=browser)
    ui.success(f"Opened 3D network ({len(persons)} nodes) in your browser.")
    ui.console.print(f"[dim]Generated: {path}[/dim]")


def cmd_viz_filter(
    ctx: typer.Context,
    type_: str,
    browser: Optional[str] = typer.Option(
        None, "--browser", "-b",
        help="Browser to open (e.g. firefox, chrome). Defaults to config viz.browser, then the system default.",
    ),
) -> None:
    persons = load_persons(ctx)
    browser = browser or ctx.obj.config.get("viz", {}).get("browser")
    path = renderer.visualize(persons, ctx.obj.config, filter_type=type_, open_browser=True, browser=browser)
    ui.success(f"Opened filtered 3D network (type='{type_}') in your browser.")
    ui.console.print(f"[dim]Generated: {path}[/dim]")


# --------------------------------------------------------------------------
# E. Repair
# --------------------------------------------------------------------------
def cmd_repair(ctx: typer.Context) -> None:
    persons = load_persons(ctx)
    orphans = graph_logic.find_orphans(persons)
    removed, affected = graph_logic.repair(persons)

    if orphans:
        save_many(ctx, list(persons.values()))
        ui.success(f"Removed {removed} orphaned connection(s) across {affected} person(s).")
        for pid, target in orphans:
            ui.console.print(f"  [dim]{persons[pid].name} → {target}[/dim]")
    else:
        ui.success("No orphaned connections found.")


# --------------------------------------------------------------------------
# F. Export
# --------------------------------------------------------------------------
def cmd_export(
    ctx: typer.Context,
    out_dir: Optional[str] = typer.Option(
        None, "--out", "-o",
        help="Output directory. Defaults to <data-dir>/markdown.",
    ),
) -> None:
    persons = load_persons(ctx)
    if not persons:
        ui.warn("No people to export.")
        return
    target = Path(out_dir) if out_dir else ctx.obj.data_dir / "markdown"
    count = exporter.export_markdown(persons, target)
    ui.success(f"Exported {count} people to {target}")
