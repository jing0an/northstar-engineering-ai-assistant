import os

from app.agent.llm.base import LLMMessage, LLMProvider


def create_llm_provider() -> LLMProvider:
    """Create the configured provider without coupling callers to its SDK."""
    provider_name = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    if provider_name == "deepseek":
        from app.agent.llm.deepseek import DeepSeekProvider

        return DeepSeekProvider()
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider_name}")


__all__ = ["LLMMessage", "LLMProvider", "create_llm_provider"]
