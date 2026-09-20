import os
import unittest
from unittest.mock import patch

from app.agent.llm.base import LLMMessage, LLMProvider
from app.agent.llm.deepseek import DeepSeekProvider


class FakeProvider:
    def generate(self, messages: list[LLMMessage]) -> str:
        return messages[-1]["content"]


class LLMProviderTest(unittest.TestCase):
    def test_provider_protocol_can_be_implemented(self) -> None:
        provider: LLMProvider = FakeProvider()
        self.assertEqual(
            provider.generate([{"role": "user", "content": "hello"}]), "hello"
        )

    def test_deepseek_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                DeepSeekProvider()


if __name__ == "__main__":
    unittest.main()
