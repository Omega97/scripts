"""Filesystem storage for Person JSON files.

Each person is stored as an individual ``{slug}_{id}.json`` file inside a
persons directory, where ``slug`` is a filesystem-safe version of the person's
name (e.g. ``omar_fait``) and ``id`` is their random numeric id. Writes are
atomic (write to temp file, then replace) to reduce the chance of corrupting
data.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Person


class StorageError(Exception):
    """Raised when a person file cannot be read or written."""


def slugify(name: str) -> str:
    """Convert a name to a filesystem-safe slug (lowercase, ASCII, underscores)."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return name or "person"


class Storage:
    def __init__(self, persons_dir: Path):
        self.persons_dir = Path(persons_dir)
        self.persons_dir.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------
    def path_for(self, person: Person) -> Path:
        return self.persons_dir / f"{slugify(person.name)}_{person.id}.json"

    def _file_for_id(self, person_id: str) -> Optional[Path]:
        matches = list(self.persons_dir.glob(f"*_{person_id}.json"))
        return matches[0] if matches else None

    # -- read ----------------------------------------------------------
    def load(self, person_id: str) -> Optional[Person]:
        path = self._file_for_id(person_id)
        if path is None:
            return None
        return Person.model_validate_json(path.read_text(encoding="utf-8"))

    def load_all(self) -> Tuple[Dict[str, Person], List[str]]:
        """Load every person file.

        Returns ``(persons, errors)`` where ``persons`` maps id -> Person and
        ``errors`` is a list of human-readable descriptions for files that
        could not be parsed (corrupted, invalid schema, etc.).
        """
        persons: Dict[str, Person] = {}
        errors: List[str] = []
        for path in sorted(self.persons_dir.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                person = Person.model_validate_json(path.read_text(encoding="utf-8"))
                persons[person.id] = person
            except Exception as exc:  # noqa: BLE001 - report any parse error
                errors.append(f"{path.name}: {exc}")
        return persons, errors

    def list_ids(self) -> List[str]:
        ids: List[str] = []
        for path in self.persons_dir.glob("*.json"):
            if path.name.startswith("."):
                continue
            try:
                person = Person.model_validate_json(path.read_text(encoding="utf-8"))
                ids.append(person.id)
            except Exception:
                continue
        return sorted(ids)

    # -- write ---------------------------------------------------------
    def save(self, person: Person) -> None:
        """Write a person to disk atomically, removing any stale file for the
        same id (e.g. after a rename)."""
        target = self.path_for(person)
        existing = self._file_for_id(person.id)

        data = person.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.persons_dir), prefix=".tmp_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
                fh.write("\n")
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

        if existing is not None and existing != target:
            try:
                existing.unlink()
            except OSError:
                pass

    def delete(self, person_id: str) -> bool:
        path = self._file_for_id(person_id)
        if path is None:
            return False
        path.unlink()
        return True

    def count(self) -> int:
        return len(self.list_ids())
