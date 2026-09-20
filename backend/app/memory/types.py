"""Enumerations used by the A2.1 memory data model."""

from enum import Enum


class MemoryScope(str, Enum):
    USER = "user"
    PROJECT = "project"
    CONVERSATION = "conversation"


class MemoryType(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    CONTEXT = "context"
    TASK = "task"
    EXPERIENCE = "experience"


class MemorySource(str, Enum):
    USER_CONFIRMED = "user_confirmed"
    USER_PROVIDED = "user_provided"
    CONVERSATION = "conversation"
    AGENT_INFERRED = "agent_inferred"
    SYSTEM = "system"