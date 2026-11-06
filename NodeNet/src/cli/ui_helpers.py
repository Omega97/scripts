"""Console UI helpers built on Rich."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from ..core.models import Person

console = Console()

STATUS_STYLES = {
    "active": "green",
    "inactive": "dim",
    "archived": "red",
}
STRENGTH_STYLES = {
    "weak": "dim",
    "medium": "yellow",
    "strong": "bold green",
}


def success(msg: str) -> None:
    console.print(f"[green]✔[/green] {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {msg}")


def error(msg: str) -> None:
    console.print(f"[red]✖[/red] {msg}")


def status_text(status: str) -> Text:
    style = STATUS_STYLES.get(status, "white")
    return Text(status, style=style)


def strength_text(strength: str) -> Text:
    style = STRENGTH_STYLES.get(strength, "white")
    return Text(strength, style=style)


def print_person(person: Person, storage_names: Optional[Dict[str, str]] = None) -> None:
    """Render a nicely formatted summary of a single person."""
    storage_names = storage_names or {}

    body_lines: List[str] = []
    if person.description:
        body_lines.append(f"[i]{escape(person.description)}[/i]")
    body_lines.append(f"Status: {status_text(person.current_status)}")

    info = person.information
    info_lines: List[str] = []
    if info.email:
        info_lines.append(f"Email:    {escape(info.email)}")
    if info.phone:
        info_lines.append(f"Phone:    {escape(info.phone)}")
    if info.gender:
        info_lines.append(f"Gender:   {escape(info.gender)}")
    if info.locations:
        info_lines.append(f"Location: {escape(', '.join(info.locations))}")
    if info.linkedin:
        info_lines.append(f"LinkedIn: {escape(info.linkedin)}")
    if info.tags:
        info_lines.append(f"Tags:     {escape(', '.join('#' + t for t in info.tags))}")
    if info_lines:
        body_lines.append("\n".join(info_lines))

    conn_lines: List[str] = []
    for conn in person.connections:
        target_name = storage_names.get(conn.target_id, conn.target_id)
        line = (
            f"• {escape(target_name)}  "
            f"[dim]{escape('[' + conn.type + ']')}[/dim] ({strength_text(conn.strength)})"
        )
        if conn.notes:
            line += f"\n    {escape(conn.notes)}"
        conn_lines.append(line)
    if conn_lines:
        body_lines.append("[bold]Connections:[/bold]")
        body_lines.extend(conn_lines)

    body_lines.append(
        f"[dim]ID: {escape(person.id)} · created {escape(person.metadata.created_at)} · "
        f"updated {escape(person.metadata.last_updated)}[/dim]"
    )

    panel = Panel(
        "\n".join(body_lines),
        title=f"[bold]{escape(person.name)}[/bold]",
        border_style="cyan",
        box=box.ROUNDED,
    )
    console.print(panel)


def build_person_table(persons: Iterable[Person]) -> Table:
    table = Table(
        title="People",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Description", style="dim")
    table.add_column("Tags", style="magenta")
    table.add_column("Conn", justify="right")
    table.add_column("ID", style="dim", no_wrap=True)

    for i, p in enumerate(persons, start=1):
        tags = ", ".join(p.information.tags) if p.information.tags else "—"
        desc = (p.description or "—").replace("\n", " ")
        table.add_row(
            str(i),
            escape(p.name),
            status_text(p.current_status),
            escape(desc),
            escape(tags),
            str(len(p.connections)),
            escape(p.id),
        )
    return table


def prompt_text(message: str, default: Optional[str] = None, allow_empty: bool = True) -> Optional[str]:
    value = Prompt.ask(message, default=default)
    if not value and not allow_empty:
        return None
    return value or None


def prompt_choice(message: str, choices: List[str], default: Optional[str] = None) -> str:
    return Prompt.ask(message, choices=choices, default=default)


def confirm(message: str, default: bool = False) -> bool:
    return Confirm.ask(message, default=default)
