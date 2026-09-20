from typing import Any, Protocol, Sequence, TypedDict

from app.agent.protocol import LLMResponse


class LLMMessage(TypedDict, total=False):
    """Provider-neutral chat message with role-specific optional fields."""

    role: str
    content: str | None
    tool_calls: list[dict[str, Any]]
    tool_call_id: str


class LLMToolSchema(TypedDict):
    type: str
    function: dict[str, Any]


class LLMProvider(Protocol):
    def generate(self, messages: Sequence[LLMMessage]) -> str:
        """Generate one text response from a chat message sequence."""
        ...

    def generate_with_tools(
        self, messages: Sequence[LLMMessage], tools: Sequence[LLMToolSchema]
    ) -> LLMResponse:
        """Generate text or structured tool calls using provider tool schemas."""
        ...
