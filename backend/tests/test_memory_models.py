import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from app.memory import Memory, MemoryScope, MemorySource, MemoryType


class MemoryModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.created = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        self.updated = self.created + timedelta(minutes=1)

    def make(self, **overrides):
        values = {
            "memory_id": "memory-001",
            "scope": "user",
            "user_id": "user-001",
            "content": "用户希望回答给出依据",
            "memory_type": "preference",
            "source": "user_confirmed",
            "confidence": 1.0,
            "created_at": self.created,
            "updated_at": self.updated,
        }
        values.update(overrides)
        return Memory(**values)

    def test_user_memory(self) -> None:
        memory = self.make()
        self.assertEqual(memory.scope, MemoryScope.USER)
        self.assertEqual(memory.memory_type, MemoryType.PREFERENCE)
        self.assertEqual(memory.source, MemorySource.USER_CONFIRMED)

    def test_project_memory_requires_project_and_user(self) -> None:
        memory = self.make(scope="project", project_id="project-001", memory_type="fact")
        self.assertEqual(memory.project_id, "project-001")
        with self.assertRaises(ValidationError):
            self.make(scope="project")
        with self.assertRaises(ValidationError):
            self.make(scope="project", project_id="project-001", user_id=None)

    def test_conversation_memory_allows_optional_project(self) -> None:
        memory = self.make(scope="conversation", memory_type="context")
        self.assertIsNone(memory.project_id)
        memory = self.make(scope="conversation", project_id="project-001")
        self.assertEqual(memory.project_id, "project-001")

    def test_invalid_scope_type_and_source_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.make(scope="system")
        with self.assertRaises(ValidationError):
            self.make(memory_type="unknown")
        with self.assertRaises(ValidationError):
            self.make(source="llm")

    def test_all_memory_types_are_expressible(self) -> None:
        for memory_type in ("fact", "preference", "context", "task", "experience"):
            self.assertEqual(self.make(memory_type=memory_type).memory_type.value, memory_type)

    def test_confidence_is_bounded(self) -> None:
        with self.assertRaises(ValidationError):
            self.make(confidence=-0.01)
        with self.assertRaises(ValidationError):
            self.make(confidence=1.01)
        self.assertEqual(self.make(confidence=0).confidence, 0)
        self.assertEqual(self.make(confidence=1).confidence, 1)

    def test_content_and_scope_identifiers_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            self.make(content="   ")
        with self.assertRaises(ValidationError):
            self.make(user_id=None)
        with self.assertRaises(ValidationError):
            self.make(memory_id=" ")

    def test_memory_id_is_nonempty_and_timestamps_are_datetime(self) -> None:
        memory = self.make(memory_id="unique-id")
        self.assertTrue(memory.memory_id)
        self.assertIsInstance(memory.created_at, datetime)
        self.assertIsInstance(memory.updated_at, datetime)
        self.assertEqual(memory.created_at.tzinfo, timezone.utc)
        with self.assertRaises(ValidationError):
            self.make(created_at=datetime(2026, 9, 1), updated_at=self.updated)

    def test_updated_at_cannot_precede_created_at(self) -> None:
        with self.assertRaises(ValidationError):
            self.make(created_at=self.updated, updated_at=self.created)


if __name__ == "__main__":
    unittest.main()