from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str


class ToolCall(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None


class ToolResult(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool: str
    result: dict[str, Any]


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolRouteResult(BaseModel):
    """The structured handoff from Tool Router back to the Orchestrator."""

    tool_call: ToolCall
    tool_result: ToolResult

    @property
    def tool(self) -> str:
        return self.tool_result.tool

    @property
    def result(self) -> dict[str, Any]:
        return self.tool_result.result

    def __getitem__(self, key: str) -> Any:
        """Keep the previous dict-style access for existing callers/tests."""
        if key == "tool":
            return self.tool
        if key == "result":
            return self.result
        return getattr(self, key)
