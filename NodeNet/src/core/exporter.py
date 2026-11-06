"""Export the dataset to Obsidian-friendly Markdown.

Each person becomes a ``{name}.md`` document with YAML frontmatter (id, status,
tags) and an ``## Connections`` section whose entries are ``[[wikilinks]]``, so
Obsidian's graph view links people automatically.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from .models import Person


def sanitize_stem(name: str) -> str:
    """Return a filesystem-safe note name (no extension)."""
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")
    return name or "untitled"


def _frontmatter(person: Person) -> str:
    lines: List[str] = ["---", f"id: {person.id}", f"status: {person.current_status}"]
    if person.information.tags:
        lines.append("tags:")
        for tag in person.information.tags:
            lines.append(f'  - "{tag}"')
    lines.append("---")
    return "\n".join(lines)


def person_to_markdown(person: Person, stem_map: Dict[str, str]) -> str:
    lines: List[str] = [_frontmatter(person), "", f"# {person.name}", ""]

    if person.description:
        lines.append(person.description)
        lines.append("")

    info = person.information
    bullets: List[str] = []
    if info.email:
        bullets.append(f"- **Email:** {info.email}")
    if info.phone:
        bullets.append(f"- **Phone:** {info.phone}")
    if info.gender:
        bullets.append(f"- **Gender:** {info.gender}")
    if info.locations:
        bullets.append(f"- **Location:** {', '.join(info.locations)}")
    if info.linkedin:
        bullets.append(f"- **LinkedIn:** [Link]({info.linkedin})")
    if bullets:
        lines.extend(bullets)
        lines.append("")

    if person.connections:
        lines.append("## Connections")
        lines.append("")
        for conn in person.connections:
            target_stem = stem_map.get(conn.target_id)
            if target_stem:
                line = f"- [[{target_stem}]] — {conn.type} · {conn.strength}"
                if conn.notes:
                    line += f" — {conn.notes}"
                lines.append(line)
            else:
                lines.append(f"- *(missing: {conn.target_id})* — {conn.type}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def export_markdown(persons: Dict[str, Person], out_dir: Path) -> int:
    """Write one Markdown file per person into ``out_dir``. Returns count."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build a unique note name for every person id.
    stem_map: Dict[str, str] = {}
    used: set = set()
    for pid in sorted(persons):
        base = sanitize_stem(persons[pid].name)
        stem = base
        if stem.lower() in used:
            stem = f"{base}_{persons[pid].id}"
        used.add(stem.lower())
        stem_map[pid] = stem

    count = 0
    for pid in sorted(persons):
        markdown = person_to_markdown(persons[pid], stem_map)
        (out_dir / f"{stem_map[pid]}.md").write_text(markdown, encoding="utf-8")
        count += 1
    return count
