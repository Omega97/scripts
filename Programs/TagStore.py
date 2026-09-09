#!/usr/bin/env python3
"""
TagStore: Lightweight, Hash-Based Image Tagging & Organization CLI

Optional: rich (pip install rich) for a nicer UI. Falls back to plain stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile

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

DB_FILE = ".tagstore.json"
SCHEMA_VERSION = 3
HASH_CHUNK = 64 * 1024
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
SKIP_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".idea",
    ".vs",
    "venvs",
}
MIN_TOKEN_LEN = 2
DEFAULT_MIN_TAG_COUNT = 2
RESULT_DISPLAY_LIMIT = 50

COMMANDS = [
    ("help", "List available commands and what they do"),
    ("scan", "Index images under the root (skips unchanged files, no full-file load)"),
    ("search", "Find images by tags: AND, OR, NOT, parentheses  e.g. dog AND cat"),
    ("tag", "Add tags to matching images     tag <query> <tags...>"),
    ("untag", "Remove tags from matching images  untag <query> <tags...>"),
    ("override", "Replace tags on matching images   override <query> <tags...>"),
    ("list", "Show every known tag with hit counts (and synonyms, if any)"),
    ("exit", "Leave the interactive prompt (aliases: quit)"),
]


def get_default_schema():
    return {
        "version": SCHEMA_VERSION,
        "settings": {"min_tag_count_for_search": DEFAULT_MIN_TAG_COUNT},
        "tags": {},
        "hashes": {},
    }


def normalize_tag(tag):
    return str(tag).strip().lower().replace(" ", "_")


def _unique_keep_order(items):
    seen = set()
    out = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _as_tag_record(value):
    """Normalize a global tag entry. Old DBs stored a synonym list; now {synonyms, count}."""
    if isinstance(value, dict):
        synonyms = value.get("synonyms", [])
        if not isinstance(synonyms, list):
            synonyms = []
        try:
            count = int(value.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        value["synonyms"] = synonyms
        value["count"] = max(0, count)
        return value
    synonyms = value if isinstance(value, list) else []
    return {"synonyms": synonyms, "count": 0}


def rebuild_tag_counts(data):
    """Count how many unique assets carry each tag. Metadata only — no image I/O."""
    counts = {}
    for info in (data.get("hashes") or {}).values():
        if not isinstance(info, dict):
            continue
        seen = set()
        for raw in info.get("tags") or []:
            tag = normalize_tag(raw)
            if tag:
                seen.add(tag)
        for tag in seen:
            counts[tag] = counts.get(tag, 0) + 1

    tags = data.setdefault("tags", {})
    if not isinstance(tags, dict):
        tags = {}
        data["tags"] = tags

    for tag in list(tags):
        tags[tag] = _as_tag_record(tags[tag])
        tags[tag]["count"] = counts.get(tag, 0)
    for tag, n in counts.items():
        if tag not in tags:
            tags[tag] = {"synonyms": [], "count": n}
        else:
            tags[tag]["count"] = n
    return counts


def migrate_schema(data):
    """Upgrade older .tagstore.json files in place without dropping fields."""
    if not isinstance(data, dict):
        raise ValueError("database root must be a JSON object")

    data.setdefault("version", 1)
    data.setdefault("settings", {})
    if not isinstance(data["settings"], dict):
        data["settings"] = {}
    data["settings"].setdefault("min_tag_count_for_search", DEFAULT_MIN_TAG_COUNT)
    data.setdefault("tags", {})
    data.setdefault("hashes", {})
    if not isinstance(data["tags"], dict):
        data["tags"] = {}
    if not isinstance(data["hashes"], dict):
        data["hashes"] = {}

    for h, info in list(data["hashes"].items()):
        if not isinstance(info, dict):
            data["hashes"][h] = {
                "path": "",
                "paths": [],
                "tags": [],
                "files": {},
            }
            continue
        paths = []
        raw_paths = info.get("paths")
        if isinstance(raw_paths, list):
            paths.extend(str(p).replace("\\", "/") for p in raw_paths if p)
        elif isinstance(raw_paths, str) and raw_paths:
            paths.append(raw_paths.replace("\\", "/"))
        single = info.get("path")
        if isinstance(single, str) and single:
            paths.insert(0, single.replace("\\", "/"))
        info["paths"] = _unique_keep_order(paths)
        info["path"] = info["paths"][0] if info["paths"] else ""
        tags = info.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        info["tags"] = _unique_keep_order(normalize_tag(t) for t in tags)
        files = info.get("files")
        if not isinstance(files, dict):
            files = {}
        cleaned = {}
        for p, meta in files.items():
            if not isinstance(meta, dict):
                continue
            cleaned[str(p).replace("\\", "/")] = {
                "size": int(meta["size"]) if "size" in meta else None,
                "mtime_ns": int(meta["mtime_ns"]) if "mtime_ns" in meta else None,
            }
        info["files"] = cleaned

    for tag, value in list(data["tags"].items()):
        data["tags"][tag] = _as_tag_record(value)

    rebuild_tag_counts(data)
    data["version"] = SCHEMA_VERSION
    return data


class TagStoreDB:
    def __init__(self, root_dir="."):
        self.root_dir = os.path.abspath(root_dir)
        self.db_path = os.path.join(self.root_dir, DB_FILE)
        self.data = self._load()

    def _min_visible_count(self):
        """Tags with fewer hits than this are treated as spurious (default: count > 1)."""
        settings = self.data.get("settings") or {}
        try:
            value = int(settings.get("min_tag_count_for_search", DEFAULT_MIN_TAG_COUNT))
        except (TypeError, ValueError):
            value = DEFAULT_MIN_TAG_COUNT
        return max(1, value)

    def tag_count(self, tag):
        rec = (self.data.get("tags") or {}).get(normalize_tag(tag))
        if isinstance(rec, dict):
            try:
                return int(rec.get("count") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def visible_tags(self, tags):
        threshold = self._min_visible_count()
        return [t for t in tags if self.tag_count(t) >= threshold]

    def _load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return migrate_schema(data)
            except Exception as e:
                console.print(f"[red]Error loading database: {e}[/red]")
                sys.exit(1)
        return get_default_schema()

    def save(self):
        payload = json.dumps(self.data, indent=2, ensure_ascii=False)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".tagstore.",
            suffix=".tmp",
            dir=self.root_dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.db_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def add_tag_to_global(self, tag):
        tag = normalize_tag(tag)
        if not tag:
            return
        existing = self.data["tags"].get(tag)
        if existing is None:
            self.data["tags"][tag] = {"synonyms": [], "count": 0}
        else:
            self.data["tags"][tag] = _as_tag_record(existing)

    def compute_hash(self, filepath):
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(HASH_CHUNK)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()

    def infer_tags(self, rel_path):
        parts = rel_path.replace("\\", "/").split("/")
        tags = set()
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                part = os.path.splitext(part)[0]
            for token in re.split(r"[_\-\s]+", part):
                token = normalize_tag(token)
                if token and len(token) >= MIN_TOKEN_LEN and re.match(r"^[a-z0-9_]+$", token):
                    tags.add(token)
        return tags

    def _rel(self, filepath):
        return os.path.relpath(filepath, self.root_dir).replace("\\", "/")

    def _iter_image_paths(self):
        """Yield image paths without keeping the whole tree in RAM."""
        for root, dirs, files in os.walk(self.root_dir, topdown=True):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if os.path.splitext(name)[1].lower() in SUPPORTED_EXTS:
                    yield os.path.join(root, name)

    def _path_cache(self):
        """rel_path -> (hash, size, mtime_ns) from the existing index."""
        cache = {}
        for h, info in self.data["hashes"].items():
            files = info.get("files") or {}
            for rel in info.get("paths") or []:
                meta = files.get(rel) or {}
                cache[rel] = (h, meta.get("size"), meta.get("mtime_ns"))
        return cache

    def _ensure_entry(self, file_hash):
        entry = self.data["hashes"].get(file_hash)
        if not isinstance(entry, dict):
            entry = {"path": "", "paths": [], "tags": [], "files": {}}
            self.data["hashes"][file_hash] = entry
        entry.setdefault("paths", [])
        entry.setdefault("tags", [])
        entry.setdefault("files", {})
        if not isinstance(entry["files"], dict):
            entry["files"] = {}
        return entry

    def _merge_location(self, file_hash, rel_path, size, mtime_ns, infer=False):
        """Attach a path to a hash and union tags (duplicate copies share one record)."""
        entry = self._ensure_entry(file_hash)
        paths = _unique_keep_order(list(entry.get("paths") or []) + [rel_path])
        entry["paths"] = paths
        entry["path"] = paths[0]
        entry.setdefault("files", {})
        entry["files"][rel_path] = {"size": size, "mtime_ns": mtime_ns}

        tags = set(entry.get("tags") or [])
        if infer:
            tags.update(self.infer_tags(rel_path))
        entry["tags"] = sorted(tags)
        for tag in tags:
            self.add_tag_to_global(tag)
        return entry

    def scan(self):
        console.print(Panel("[bold cyan]Scanning for images…[/bold cyan]", title="TagStore"))
        cache = self._path_cache()
        seen_hashes = set()
        seen_paths = set()
        hashed = 0
        reused = 0
        merged = 0
        errors = 0
        new_assets = 0

        # Count names only (cheap), then walk again so we never hold the file list.
        total = sum(1 for _ in self._iter_image_paths())

        if total == 0:
            console.print("[yellow]No supported images found.[/yellow]")
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Indexing", total=total)
                for filepath in self._iter_image_paths():
                    try:
                        rel = self._rel(filepath)
                        st = os.stat(filepath)
                        size, mtime_ns = st.st_size, st.st_mtime_ns
                        cached = cache.get(rel)
                        if (
                            cached
                            and cached[1] == size
                            and cached[2] == mtime_ns
                            and cached[0] in self.data["hashes"]
                        ):
                            file_hash = cached[0]
                            reused += 1
                            is_new_path = False
                        else:
                            file_hash = self.compute_hash(filepath)
                            hashed += 1
                            is_new_path = rel not in (self.data["hashes"].get(file_hash, {}).get("paths") or [])

                        existed = file_hash in self.data["hashes"]
                        if existed and is_new_path:
                            merged += 1
                        if not existed:
                            new_assets += 1

                        infer = (not existed) or is_new_path
                        self._merge_location(file_hash, rel, size, mtime_ns, infer=infer)
                        seen_hashes.add(file_hash)
                        seen_paths.add(rel)
                    except OSError as e:
                        errors += 1
                        console.print(f"[yellow]Skipped {filepath}: {e}[/yellow]")
                    progress.update(task, advance=1)

        stale_hashes = []
        for h, info in self.data["hashes"].items():
            keep = [p for p in (info.get("paths") or []) if p in seen_paths]
            if not keep:
                stale_hashes.append(h)
                continue
            info["paths"] = keep
            info["path"] = keep[0]
            files_meta = info.get("files") or {}
            info["files"] = {p: files_meta[p] for p in keep if p in files_meta}

        for h in stale_hashes:
            del self.data["hashes"][h]

        counts = rebuild_tag_counts(self.data)
        frequent = sum(1 for n in counts.values() if n >= self._min_visible_count())

        self.save()

        summary = Table(box=box.SIMPLE, show_header=False, title="Scan complete")
        summary.add_column("k", style="dim")
        summary.add_column("v")
        summary.add_row("Unique assets", str(len(self.data["hashes"])))
        summary.add_row("Files seen", str(len(seen_paths)))
        summary.add_row("Hashed (changed/new)", str(hashed))
        summary.add_row("Unchanged (hash skipped)", str(reused))
        summary.add_row("Duplicates merged", str(merged))
        summary.add_row("New assets", str(new_assets))
        summary.add_row("Tags (total)", str(len(counts)))
        summary.add_row(f"Tags with {self._min_visible_count()}+ hits", str(frequent))
        if errors:
            summary.add_row("Unreadable", str(errors))
        console.print(summary)

    def search(self, query_str):
        tokens = re.findall(r"\(|\)|AND|OR|NOT|[a-zA-Z0-9_]+", query_str.upper())
        pos = 0

        def parse_or():
            nonlocal pos
            left = parse_and()
            while pos < len(tokens) and tokens[pos] == "OR":
                pos += 1
                right = parse_and()
                left = lambda tags, l=left, r=right: l(tags) or r(tags)
            return left

        def parse_and():
            nonlocal pos
            left = parse_not()
            while pos < len(tokens) and tokens[pos] not in (")", "OR"):
                if tokens[pos] == "AND":
                    pos += 1
                    if pos >= len(tokens) or tokens[pos] in (")", "OR"):
                        break
                right = parse_not()
                left = lambda tags, l=left, r=right: l(tags) and r(tags)
            return left

        def parse_not():
            nonlocal pos
            if pos < len(tokens) and tokens[pos] == "NOT":
                pos += 1
                operand = parse_primary()
                return lambda tags, op=operand: not op(tags)
            return parse_primary()

        def parse_primary():
            nonlocal pos
            if pos < len(tokens) and tokens[pos] == "(":
                pos += 1
                res = parse_or()
                if pos < len(tokens) and tokens[pos] == ")":
                    pos += 1
                return res
            if pos < len(tokens):
                tag = tokens[pos].lower()
                pos += 1
                return lambda tags, t=tag: t in tags
            return lambda tags: True

        if not tokens:
            return []

        try:
            matcher = parse_or()
        except Exception:
            console.print("[red]Invalid search query syntax.[/red]")
            return []

        results = []
        for h, info in self.data["hashes"].items():
            if not isinstance(info, dict):
                continue
            if matcher(set(info.get("tags") or [])):
                results.append((h, info))
        return results

    def modify_tags(self, query_str, tags_to_add=None, tags_to_remove=None, override=False):
        results = self.search(query_str)
        if not results:
            console.print("[yellow]No assets matched the query.[/yellow]")
            return

        tags_to_add = [normalize_tag(t) for t in (tags_to_add or []) if normalize_tag(t)]
        tags_to_remove = [normalize_tag(t) for t in (tags_to_remove or []) if normalize_tag(t)]

        for h, info in results:
            if override:
                current_tags = set()
            else:
                current_tags = set(info.get("tags") or [])
            current_tags.update(tags_to_add)
            current_tags.difference_update(tags_to_remove)
            info["tags"] = sorted(current_tags)
            for t in tags_to_add:
                self.add_tag_to_global(t)

        rebuild_tag_counts(self.data)
        self.save()
        console.print(f"[bold green]Updated tags for {len(results)} asset(s).[/bold green]")

    def list_tags(self):
        threshold = self._min_visible_count()
        table = Table(title="Global Tags", box=box.ROUNDED, show_lines=False)
        table.add_column("Tag", style="cyan", no_wrap=True)
        table.add_column("Hits", justify="right", style="yellow")
        table.add_column("Synonyms / Related", style="magenta")

        if not self.data["tags"]:
            table.add_row("—", "0", "(none yet — run [bold]scan[/bold])")
        else:
            rows = []
            for tag, rec in self.data["tags"].items():
                rec = _as_tag_record(rec)
                synonyms = rec.get("synonyms") or []
                rows.append((rec.get("count", 0), tag, synonyms))
            rows.sort(key=lambda r: (-r[0], r[1]))
            for count, tag, synonyms in rows:
                syn = ", ".join(synonyms) if synonyms else "—"
                label = tag if count >= threshold else f"[dim]{tag}[/dim]"
                table.add_row(label, str(count), syn)

        console.print(table)
        console.print(
            f"[dim]Image views hide tags with fewer than {threshold} hits "
            f"(settings.min_tag_count_for_search).[/dim]"
        )

    def show_results(self, results):
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
            shown_tags = self.visible_tags(info.get("tags") or [])
            table.add_row(h[:12] + "…", loc, ", ".join(shown_tags) if shown_tags else "—")

        console.print(table)
        if extra:
            console.print(f"[dim]… {extra} more not shown (narrow the query)[/dim]")


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
        "[green]tag dog favorite[/green]   [green]scan[/green]\n"
        "[dim]One-shot from a shell:[/dim]  [green]tagstore search dog AND cat[/green]"
    )


def dispatch(db, command, argv):
    command = (command or "").lower()
    if command in ("help", "?"):
        print_command_help()
        return 0
    if command == "scan":
        db.scan()
        return 0
    if command == "search":
        query = " ".join(argv).strip()
        if not query:
            console.print("[red]Usage:[/red] search <query>")
            return 1
        db.show_results(db.search(query))
        return 0
    if command in ("tag", "untag", "override"):
        if len(argv) < 2:
            console.print(f"[red]Usage:[/red] {command} <query> <tags...>")
            return 1
        query, tags = argv[0], argv[1:]
        if command == "tag":
            db.modify_tags(query, tags_to_add=tags)
        elif command == "untag":
            db.modify_tags(query, tags_to_remove=tags)
        else:
            db.modify_tags(query, tags_to_add=tags, override=True)
        return 0
    if command == "list":
        db.list_tags()
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

    p_tag = sub.add_parser("tag", help="Add tags to matched images")
    p_tag.add_argument("query", help="Search query to target images")
    p_tag.add_argument("tags", nargs="+", help="Tags to add")

    p_untag = sub.add_parser("untag", help="Remove tags from matched images")
    p_untag.add_argument("query", help="Search query to target images")
    p_untag.add_argument("tags", nargs="+", help="Tags to remove")

    p_override = sub.add_parser("override", help="Clear auto-tags and set custom tags")
    p_override.add_argument("query", help="Search query to target images")
    p_override.add_argument("tags", nargs="+", help="Custom tags to apply")

    sub.add_parser("list", help="List all global tags")
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("help", "?"):
        print_command_help()
        return 0

    db = TagStoreDB(args.root)

    if not args.command:
        return run_repl(db)

    rest = []
    if args.command == "search":
        rest = args.query
    elif args.command in ("tag", "untag", "override"):
        rest = [args.query, *args.tags]

    code = dispatch(db, args.command, rest)
    return 0 if code in (0, -1) else code


if __name__ == "__main__":
    sys.exit(main())
