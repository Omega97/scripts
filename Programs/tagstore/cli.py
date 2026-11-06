"""Command-line and REPL interface for TagStore.

This module is a thin presentation layer over :mod:`tagstore.model`. It owns
rich formatting and argument parsing; all logic lives in the model.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys

from .errors import NoMatchError, QuerySyntaxError
from .model import TagStore

try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import (
        Progress,
        SpinnerColumn,
        TextColumn,
        BarColumn,
        MofNCompleteColumn,
        TimeElapsedColumn,
    )
    from rich.panel import Panel
    from rich import box

    console = Console()
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

    _MARKUP = re.compile(r"\[/?[^\]]+\]")

    def _plain(text):
        return _MARKUP.sub("", str(text))

    class Console:
        def print(self, *args, **kwargs):
            print(*(_plain(a) for a in args))

        def log(self, *args, **kwargs):
            self.print(*args)

        def input(self, prompt="", **kwargs):
            return input(_plain(prompt))

    class Panel:
        def __init__(self, renderable, *args, **kwargs):
            self.renderable = renderable
            self.title = kwargs.get("title") or ""

        def __str__(self):
            if self.title:
                return f"{self.title}\n{self.renderable}"
            return str(self.renderable)

    class Table:
        def __init__(self, title="", box=None, show_lines=False, **kwargs):
            self.title = title
            self._columns = []
            self._rows = []

        def add_column(self, name, **kwargs):
            self._columns.append(name)

        def add_row(self, *values):
            self._rows.append(values)

        def __str__(self):
            lines = []
            if self.title:
                lines.append(self.title)
                lines.append("-" * len(self.title))
            if self._columns:
                lines.append(" | ".join(self._columns))
            for row in self._rows:
                lines.append(" | ".join(str(v).replace("\n", " · ") for v in row))
            return "\n".join(lines) if lines else "(empty)"

    class _NoOpColumn:
        def __init__(self, *args, **kwargs):
            pass

    SpinnerColumn = TextColumn = BarColumn = MofNCompleteColumn = TimeElapsedColumn = _NoOpColumn

    class Progress:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def add_task(self, description, total=0):
            print(description)
            return 0

        def update(self, task_id, advance=1):
            pass

    class box:
        ROUNDED = None
        SIMPLE_HEAVY = None
        SIMPLE = None

    console = Console()

RESULT_DISPLAY_LIMIT = 50

COMMANDS = [
    ("help", "List available commands and what they do"),
    ("scan", "Index images under the root (skips unchanged files, no full-file load)"),
    ("search", "Find images by tags: AND, OR, NOT, parentheses  e.g. dog AND cat"),
    ("add", "Add tags to matching images     add <query> <tags...>"),
    ("remove", "Remove tags from matching images  remove <query> <tags...>"),
    ("override", "Replace tags on matching images   override <query> <tags...>"),
    ("tags", "Show every known tag with hit counts (and synonyms, if any)"),
    ("exit", "Leave the interactive prompt (aliases: quit)"),
]


def print_command_help():
    table = Table(title="TagStore commands", box=box.ROUNDED, show_lines=False)
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Description", style="white")
    for name, desc in COMMANDS:
        table.add_row(name, desc)
    console.print(table)
    console.print(
        "[dim]Search query operators:[/dim] [bold]AND[/bold], [bold]OR[/bold], [bold]NOT[/bold], [bold]( )[/bold]\n"
        "[dim]Examples:[/dim]  [green]search dog AND cat[/green]   "
        "[green]add dog favorite[/green]   [green]scan[/green]\n"
        "[dim]One-shot from a shell:[/dim]  [green]tagstore search dog AND cat[/green]"
    )


def _show_tags(db):
    records = db.list_tags()
    threshold = db._min_visible_count()
    table = Table(title="Global Tags", box=box.ROUNDED, show_lines=False)
    table.add_column("Tag", style="cyan", no_wrap=True)
    table.add_column("Hits", justify="right", style="yellow")
    table.add_column("Synonyms / Related", style="magenta")

    if not records:
        table.add_row("—", "0", "(none yet — run [bold]scan[/bold])")
    else:
        for rec in records:
            syn = ", ".join(rec["synonyms"]) if rec["synonyms"] else "—"
            label = rec["tag"] if rec["visible"] else f"[dim]{rec['tag']}[/dim]"
            table.add_row(label, str(rec["count"]), syn)

    console.print(table)
    console.print(
        f"[dim]Tags matched fewer than {threshold} times are not treated as tags "
        f"(settings.min_tag_count_for_search).[/dim]"
    )


def show_results(db, results):
    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    shown = results[:RESULT_DISPLAY_LIMIT]
    extra = len(results) - len(shown)
    title = f"Search Results ({len(results)} unique asset{'s' if len(results) != 1 else ''})"
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("Hash", style="dim", width=12, no_wrap=True)
    table.add_column("Locations", style="cyan")
    table.add_column("Tags", style="green")

    for h, info in shown:
        paths = info.get("paths") or ([info["path"]] if info.get("path") else [])
        loc = "\n".join(paths) if paths else "—"
        shown_tags = db.visible_tags(info.get("tags") or [])
        table.add_row(h[:12] + "…", loc, ", ".join(shown_tags) if shown_tags else "—")

    console.print(table)
    if extra:
        console.print(f"[dim]… {extra} more not shown (narrow the query)[/dim]")


def _print_scan_summary(summary):
    table = Table(box=box.SIMPLE, show_header=False, title="Scan complete")
    table.add_column("k", style="dim")
    table.add_column("v")
    table.add_row("Unique assets", str(summary["assets"]))
    table.add_row("Files seen", str(summary["files_seen"]))
    table.add_row("Hashed (changed/new)", str(summary["hashed"]))
    table.add_row("Unchanged (hash skipped)", str(summary["reused"]))
    table.add_row("Duplicates merged", str(summary["merged"]))
    table.add_row("New assets", str(summary["new_assets"]))
    table.add_row("Tags (total)", str(summary["tags_total"]))
    table.add_row("Min matches per tag", str(summary["min_matches"]))
    if summary.get("cancelled"):
        table.add_row("Cancelled", "yes")
    if summary["errors"]:
        table.add_row("Unreadable", str(len(summary["errors"])))
    console.print(table)


def _run_scan(db):
    console.print(Panel("[bold cyan]Scanning for images…[/bold cyan]", title="TagStore"))
    summary = {"total": 0}
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = [None]
        last = [0]

        def cb(done, total):
            if task[0] is None:
                task[0] = progress.add_task("Indexing", total=total)
            progress.update(task[0], advance=done - last[0])
            last[0] = done

        summary = db.scan(progress_cb=cb)

    if summary["total"] == 0:
        console.print("[yellow]No supported images found.[/yellow]")
    _print_scan_summary(summary)


def dispatch(db, command, argv):
    command = (command or "").lower()
    if command in ("help", "?"):
        print_command_help()
        return 0
    if command == "scan":
        _run_scan(db)
        return 0
    if command == "search":
        query = " ".join(argv).strip()
        if not query:
            console.print("[red]Usage:[/red] search <query>")
            return 1
        try:
            results = db.search(query)
        except QuerySyntaxError:
            console.print("[red]Invalid search query syntax.[/red]")
            return 1
        show_results(db, results)
        return 0
    if command in ("add", "remove", "override"):
        if len(argv) < 2:
            console.print(f"[red]Usage:[/red] {command} <query> <tags...>")
            return 1
        query, tags = argv[0], argv[1:]
        try:
            if command == "add":
                n = db.modify_tags(query, tags_to_add=tags)
            elif command == "remove":
                n = db.modify_tags(query, tags_to_remove=tags)
            else:
                n = db.modify_tags(query, tags_to_add=tags, override=True)
        except NoMatchError:
            console.print("[yellow]No assets matched the query.[/yellow]")
            return 1
        except QuerySyntaxError:
            console.print("[red]Invalid search query syntax.[/red]")
            return 1
        console.print(f"[bold green]Updated tags for {n} asset(s).[/bold green]")
        return 0
    if command == "tags":
        _show_tags(db)
        return 0
    if command in ("exit", "quit"):
        return -1
    console.print(f"[red]Unknown command:[/red] {command}   [dim](try [bold]help[/bold])[/dim]")
    return 1


def run_repl(db):
    banner = (
        f"[bold]TagStore[/bold]  hash-based image tags\n"
        f"[dim]Root[/dim]  {db.root_dir}\n"
        f"[dim]Index[/dim] {db.db_path}\n"
        f"[dim]Type [bold]help[/bold] for commands, [bold]exit[/bold] to leave.[/dim]"
    )
    console.print(Panel(banner, box=box.ROUNDED, title="tagstore"))
    while True:
        try:
            line = console.input("[bold cyan]tagstore[/bold cyan] [dim]›[/dim] ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        line = (line or "").strip()
        if not line:
            continue
        try:
            parts = shlex.split(line, posix=os.name != "nt")
        except ValueError as e:
            console.print(f"[red]Could not parse line:[/red] {e}")
            continue
        if not parts:
            continue
        code = dispatch(db, parts[0], parts[1:])
        if code == -1:
            break
    console.print("[dim]Bye.[/dim]")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="tagstore",
        description="TagStore: hash-based image tagging. Run with no arguments for the interactive prompt.",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=True,
    )
    parser.add_argument(
        "-C",
        "--root",
        default=".",
        help="Directory to index (default: current directory)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("help", help="List available commands with descriptions")
    sub.add_parser("scan", help="Scan directory and index assets")

    p_search = sub.add_parser("search", help="Search images using logical expressions")
    p_search.add_argument("query", nargs="+", help="e.g. dog AND cat")

    p_add = sub.add_parser("add", help="Add tags to matched images")
    p_add.add_argument("query", help="Search query to target images")
    p_add.add_argument("tags", nargs="+", help="Tags to add")

    p_remove = sub.add_parser("remove", help="Remove tags from matched images")
    p_remove.add_argument("query", help="Search query to target images")
    p_remove.add_argument("tags", nargs="+", help="Tags to remove")

    p_override = sub.add_parser("override", help="Clear auto-tags and set custom tags")
    p_override.add_argument("query", help="Search query to target images")
    p_override.add_argument("tags", nargs="+", help="Custom tags to apply")

    sub.add_parser("tags", help="List all global tags")
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("help", "?"):
        print_command_help()
        return 0

    db = TagStore(args.root)

    if not args.command:
        return run_repl(db)

    rest = []
    if args.command == "search":
        rest = args.query
    elif args.command in ("add", "remove", "override"):
        rest = [args.query, *args.tags]

    code = dispatch(db, args.command, rest)
    return 0 if code in (0, -1) else code


if __name__ == "__main__":
    sys.exit(main())
