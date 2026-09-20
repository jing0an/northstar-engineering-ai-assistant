"""SQLite connection and schema management for memory persistence."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "storage" / "memory" / "memory.sqlite3"


class MemoryStore:
    """Own an isolated SQLite database used by the memory repository."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        if database_path is None:
            database_path = DEFAULT_DATABASE_PATH
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memories_user_scope
                    ON memories (user_id, scope);
                CREATE INDEX IF NOT EXISTS idx_memories_user_project
                    ON memories (user_id, project_id);
                """
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Provide a serialized transaction for one repository operation."""
        with self._lock:
            try:
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()