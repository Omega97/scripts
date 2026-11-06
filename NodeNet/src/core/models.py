"""Data models for NodeNet.

Pydantic models describing a Person and their Connections, matching the JSON
schema in the project blueprint.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["active", "inactive", "archived"]
Strength = Literal["weak", "medium", "strong"]


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """Return a random numeric id (9 digits) as a string."""
    return str(random.randint(100_000_000, 999_999_999))


class Information(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    locations: List[str] = Field(default_factory=list)
    linkedin: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class Metadata(BaseModel):
    created_at: str
    last_updated: str


class Connection(BaseModel):
    target_id: str
    type: str = "friend"
    strength: Strength = "medium"
    notes: str = ""


class Person(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    current_status: Status = "active"
    information: Information = Field(default_factory=Information)
    metadata: Metadata
    connections: List[Connection] = Field(default_factory=list)

    @classmethod
    def create(
        cls,
        name: str,
        description: str = "",
        current_status: Status = "active",
        information: Optional[Information] = None,
    ) -> "Person":
        """Build a new Person with a fresh random id and timestamps."""
        ts = now_iso()
        return cls(
            id=new_id(),
            name=name,
            description=description,
            current_status=current_status,
            information=information or Information(),
            metadata=Metadata(created_at=ts, last_updated=ts),
            connections=[],
        )

    def touch(self) -> None:
        """Mark the record as updated."""
        self.metadata.last_updated = now_iso()

    def get_connection(self, target_id: str) -> Optional[Connection]:
        for conn in self.connections:
            if conn.target_id == target_id:
                return conn
        return None

    def has_connection(self, target_id: str) -> bool:
        return self.get_connection(target_id) is not None

    def add_connection(self, conn: Connection) -> bool:
        if self.has_connection(conn.target_id):
            return False
        self.connections.append(conn)
        self.touch()
        return True

    def remove_connection(self, target_id: str) -> bool:
        before = len(self.connections)
        self.connections = [c for c in self.connections if c.target_id != target_id]
        changed = len(self.connections) != before
        if changed:
            self.touch()
        return changed
