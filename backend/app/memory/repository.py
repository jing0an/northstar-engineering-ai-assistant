"""User/project-isolated CRUD repository for Memory records."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Memory
from .store import DEFAULT_DATABASE_PATH, MemoryStore
from .types import MemoryScope, MemorySource, MemoryType


class MemoryError(Exception):
    """Base error for memory persistence operations."""


class MemoryNotFoundError(MemoryError):
    """Raised when a record is absent or outside the caller's scope."""


class MemoryAlreadyExistsError(MemoryError):
    """Raised when create would reuse an existing memory_id."""


_UNSET = object()


class MemoryRepository:
    """Persist validated Memory models with mandatory tenant isolation."""

    MAX_LIMIT = 1000

    def __init__(self, store: MemoryStore | str | Path | None = None) -> None:
        self.store = store if isinstance(store, MemoryStore) else MemoryStore(store or DEFAULT_DATABASE_PATH)

    @staticmethod
    def _required_user_id(user_id: str) -> str:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        return user_id.strip()

    @staticmethod
    def _utc_iso(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("memory timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _row_values(cls, memory: Memory) -> tuple[Any, ...]:
        return (
            memory.memory_id,
            memory.scope.value,
            memory.user_id,
            memory.project_id,
            memory.content,
            memory.memory_type.value,
            memory.source.value,
            memory.confidence,
            cls._utc_iso(memory.created_at),
            cls._utc_iso(memory.updated_at),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Memory:
        try:
            return Memory(
                memory_id=row["memory_id"],
                scope=row["scope"],
                user_id=row["user_id"],
                project_id=row["project_id"],
                content=row["content"],
                memory_type=row["memory_type"],
                source=row["source"],
                confidence=row["confidence"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        except Exception as error:
            raise MemoryError("Stored memory data is invalid") from error

    @classmethod
    def _visibility_clauses(
        cls,
        user_id: str,
        project_id: str | None,
        scope: MemoryScope | str | None,
    ) -> tuple[list[str], list[Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        normalized_scope = scope.value if isinstance(scope, MemoryScope) else scope
        if normalized_scope is not None:
            clauses.append("scope = ?")
            params.append(normalized_scope)

        if normalized_scope == MemoryScope.PROJECT.value and project_id is None:
            clauses.append("1 = 0")
        elif project_id is None:
            # A project-scoped record must never be read without its project key.
            clauses.append("scope != ?")
            params.append(MemoryScope.PROJECT.value)
            clauses.append(
                "(scope != ? OR project_id IS NULL)"
            )
            params.append(MemoryScope.CONVERSATION.value)
        else:
            # User memories are user-wide; project/conversation memories must match.
            clauses.append("(scope = ? OR project_id = ?)")
            params.extend([MemoryScope.USER.value, project_id])
        return clauses, params

    def create(self, memory: Memory) -> Memory:
        try:
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO memories
                    (memory_id, scope, user_id, project_id, content, memory_type,
                     source, confidence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._row_values(memory),
                )
        except sqlite3.IntegrityError as error:
            raise MemoryAlreadyExistsError(
                f"Memory {memory.memory_id!r} already exists"
            ) from error
        return memory

    def get(
        self,
        memory_id: str,
        user_id: str,
        project_id: str | None = None,
        scope: MemoryScope | str | None = None,
    ) -> Memory:
        user_id = self._required_user_id(user_id)
        clauses, params = self._visibility_clauses(user_id, project_id, scope)
        clauses.insert(0, "memory_id = ?")
        params.insert(0, memory_id)
        with self.store.transaction() as connection:
            row = connection.execute(
                f"SELECT * FROM memories WHERE {' AND '.join(clauses)}", params
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("Memory was not found")
        return self._from_row(row)

    def list(
        self,
        user_id: str,
        project_id: str | None = None,
        scope: MemoryScope | str | None = None,
        memory_type: MemoryType | str | None = None,
        limit: int = 100,
    ) -> list[Memory]:
        user_id = self._required_user_id(user_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if limit > self.MAX_LIMIT:
            raise ValueError(f"limit must be <= {self.MAX_LIMIT}")
        clauses, params = self._visibility_clauses(user_id, project_id, scope)
        if memory_type is not None:
            clauses.append("memory_type = ?")
            params.append(
                memory_type.value if isinstance(memory_type, MemoryType) else memory_type
            )
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at ASC, memory_id ASC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def update(
        self,
        memory_id: str,
        user_id: str,
        project_id: str | None = None,
        scope: MemoryScope | str | None = None,
        *,
        content: str | object = _UNSET,
        memory_type: MemoryType | str | object = _UNSET,
        source: MemorySource | str | object = _UNSET,
        confidence: float | object = _UNSET,
    ) -> Memory:
        current = self.get(memory_id, user_id, project_id, scope)
        values = current.model_dump()
        if content is not _UNSET:
            values["content"] = content
        if memory_type is not _UNSET:
            values["memory_type"] = memory_type
        if source is not _UNSET:
            values["source"] = source
        if confidence is not _UNSET:
            values["confidence"] = confidence
        values["updated_at"] = datetime.now(timezone.utc)
        updated = Memory(**values)
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE memories
                   SET content = ?, memory_type = ?, source = ?, confidence = ?, updated_at = ?
                 WHERE memory_id = ? AND user_id = ?
                """,
                (
                    updated.content,
                    updated.memory_type.value,
                    updated.source.value,
                    updated.confidence,
                    self._utc_iso(updated.updated_at),
                    updated.memory_id,
                    updated.user_id,
                ),
            )
        return updated

    def delete(
        self,
        memory_id: str,
        user_id: str,
        project_id: str | None = None,
        scope: MemoryScope | str | None = None,
    ) -> bool:
        # Fetch first so project/scope isolation is applied identically to get/update.
        self.get(memory_id, user_id, project_id, scope)
        clauses, params = self._visibility_clauses(user_id, project_id, scope)
        clauses.insert(0, "memory_id = ?")
        params.insert(0, memory_id)
        with self.store.transaction() as connection:
            cursor = connection.execute(
                f"DELETE FROM memories WHERE {' AND '.join(clauses)}", params
            )
        if cursor.rowcount != 1:
            raise MemoryNotFoundError("Memory was not found")
        return True

    def close(self) -> None:
        self.store.close()