import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from app.memory import (
    Memory,
    MemoryAlreadyExistsError,
    MemoryNotFoundError,
    MemoryRepository,
    MemoryScope,
    MemorySource,
    MemoryStore,
    MemoryType,
)


class MemoryRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp_dir.name) / "memory.sqlite3")
        self.repository = MemoryRepository(self.store)
        self.created = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def make(self, memory_id: str, **overrides) -> Memory:
        values = {
            "memory_id": memory_id,
            "scope": "user",
            "user_id": "user-a",
            "content": "用户希望回答给出依据",
            "memory_type": "preference",
            "source": "user_confirmed",
            "confidence": 1.0,
            "created_at": self.created,
            "updated_at": self.created,
        }
        values.update(overrides)
        return Memory(**values)

    def test_create_get_user_project_and_conversation(self) -> None:
        user = self.repository.create(self.make("u1"))
        project = self.repository.create(
            self.make("p1", scope="project", project_id="project-a", memory_type="fact")
        )
        conversation = self.repository.create(
            self.make("c1", scope="conversation", project_id="project-a", memory_type="context")
        )
        self.assertEqual(self.repository.get("u1", "user-a"), user)
        self.assertEqual(self.repository.get("p1", "user-a", "project-a"), project)
        self.assertEqual(self.repository.get("c1", "user-a", "project-a"), conversation)

    def test_duplicate_id_and_missing_are_not_found_or_duplicate(self) -> None:
        self.repository.create(self.make("same"))
        with self.assertRaises(MemoryAlreadyExistsError):
            self.repository.create(self.make("same"))
        with self.assertRaises(MemoryNotFoundError):
            self.repository.get("missing", "user-a")

    def test_user_and_project_isolation(self) -> None:
        self.repository.create(self.make("a"))
        self.repository.create(self.make("b", user_id="user-b"))
        self.repository.create(self.make("pa", scope="project", project_id="project-a"))
        self.repository.create(self.make("pb", scope="project", project_id="project-b"))
        with self.assertRaises(MemoryNotFoundError):
            self.repository.get("b", "user-a")
        with self.assertRaises(MemoryNotFoundError):
            self.repository.get("a", "user-b")
        with self.assertRaises(MemoryNotFoundError):
            self.repository.get("pa", "user-a", "project-b")
        with self.assertRaises(MemoryNotFoundError):
            self.repository.get("pa", "user-a")

    def test_list_filters_scope_type_project_and_limit(self) -> None:
        self.repository.create(self.make("user-fact", memory_type="fact"))
        self.repository.create(self.make("user-pref"))
        self.repository.create(self.make("project-fact", scope="project", project_id="project-a", memory_type="fact"))
        self.repository.create(self.make("project-other", scope="project", project_id="project-b", memory_type="fact"))
        project = self.repository.list("user-a", project_id="project-a", scope="project")
        self.assertEqual([item.memory_id for item in project], ["project-fact"])
        facts = self.repository.list("user-a", memory_type=MemoryType.FACT)
        self.assertEqual([item.memory_id for item in facts], ["user-fact"])
        self.assertEqual(len(self.repository.list("user-a", limit=1)), 1)
        with self.assertRaises(ValueError):
            self.repository.list("user-a", limit=1001)

    def test_project_scope_requires_project_key_for_access(self) -> None:
        self.repository.create(self.make("project", scope="project", project_id="project-a"))
        with self.assertRaises(MemoryNotFoundError):
            self.repository.get("project", "user-a")
        self.assertEqual(self.repository.list("user-a"), [])

    def test_update_preserves_id_and_created_at_and_updates_timestamp(self) -> None:
        original = self.repository.create(self.make("update-me"))
        updated = self.repository.update(
            "update-me", "user-a", content="新内容", confidence=0.5
        )
        self.assertEqual(updated.memory_id, original.memory_id)
        self.assertEqual(updated.created_at, original.created_at)
        self.assertEqual(updated.content, "新内容")
        self.assertEqual(updated.confidence, 0.5)
        self.assertGreaterEqual(updated.updated_at, original.updated_at)
        with self.assertRaises(MemoryNotFoundError):
            self.repository.update("update-me", "user-b", content="越权")
        with self.assertRaises(ValidationError):
            self.repository.update("update-me", "user-a", content=" ")

    def test_delete_requires_isolation(self) -> None:
        self.repository.create(self.make("delete-me"))
        with self.assertRaises(MemoryNotFoundError):
            self.repository.delete("delete-me", "user-b")
        self.assertTrue(self.repository.delete("delete-me", "user-a"))
        with self.assertRaises(MemoryNotFoundError):
            self.repository.get("delete-me", "user-a")

    def test_utc_datetime_round_trip(self) -> None:
        memory = self.repository.create(self.make("time", confidence=0.0))
        loaded = self.repository.get("time", "user-a")
        self.assertIsInstance(loaded.created_at, datetime)
        self.assertIsNotNone(loaded.created_at.tzinfo)
        self.assertEqual(loaded.created_at, memory.created_at)


if __name__ == "__main__":
    unittest.main()