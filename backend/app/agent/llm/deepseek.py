import json
import os
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from app.agent.llm.base import LLMMessage, LLMToolSchema
from app.agent.protocol import LLMResponse, ToolCall


class DeepSeekProvider:
    """DeepSeek's OpenAI-compatible chat API, kept behind the provider boundary."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not self.api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not configured. Set it before using DeepSeekProvider."
            )
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
        if not self.model:
            raise RuntimeError("DEEPSEEK_MODEL must not be empty.")

        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError(
                "The OpenAI Python SDK is required for DeepSeekProvider. "
                "Install backend requirements first."
            ) from error

        self._client: Any = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
        )

    def generate(self, messages: Sequence[LLMMessage]) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=list(messages),
        )
        content = response.choices[0].message.content
        return content or ""

    def generate_with_tools(
        self, messages: Sequence[LLMMessage], tools: Sequence[LLMToolSchema]
    ) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            tools=list(tools),
            tool_choice="auto",
        )
        message = response.choices[0].message
        tool_calls = []
        for tool_call in message.tool_calls or []:
            raw_arguments = tool_call.function.arguments
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            tool_calls.append(
                ToolCall(
                    tool=tool_call.function.name,
                    arguments=arguments,
                    call_id=getattr(tool_call, "id", None),
                )
            )
        return LLMResponse(content=message.content, tool_calls=tool_calls)
