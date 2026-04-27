import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class LlmProxyBypassTest(unittest.TestCase):
    def test_http_client_factory_disables_env_proxy(self):
        from core.http_client_factory import create_llm_async_http_client, create_llm_http_client

        client = create_llm_http_client(timeout=12.0)
        async_client = create_llm_async_http_client(timeout=34.0)
        try:
            self.assertFalse(client._trust_env)
            self.assertFalse(async_client._trust_env)
            self.assertEqual(client.timeout.connect, 12.0)
            self.assertEqual(async_client.timeout.connect, 34.0)
        finally:
            client.close()
            try:
                import asyncio

                asyncio.run(async_client.aclose())
            except RuntimeError:
                pass

    def test_qwen_model_init_passes_proxy_bypass_clients(self):
        fake_chatqwen = []

        class FakeChatQwen:
            def __init__(self, **kwargs):
                fake_chatqwen.append(kwargs)

        original_langchain_qwq = sys.modules.get("langchain_qwq")
        sys.modules["langchain_qwq"] = types.SimpleNamespace(ChatQwen=FakeChatQwen)
        try:
            if "models.factory" in sys.modules:
                del sys.modules["models.factory"]
            from models.factory import QwenModel

            with patch("models.factory.create_llm_http_client", return_value="sync-client"), patch(
                "models.factory.create_llm_async_http_client", return_value="async-client"
            ):
                model = QwenModel()
                model.init_model(True)
        finally:
            if original_langchain_qwq is None:
                sys.modules.pop("langchain_qwq", None)
            else:
                sys.modules["langchain_qwq"] = original_langchain_qwq
            sys.modules.pop("models.factory", None)

        self.assertEqual(len(fake_chatqwen), 1)
        kwargs = fake_chatqwen[0]
        self.assertEqual(kwargs["http_client"], "sync-client")
        self.assertEqual(kwargs["http_async_client"], "async-client")
        self.assertTrue(kwargs["streaming"])

    def test_llm_factory_passes_proxy_bypass_clients(self):
        fake_chatqwen = []

        class FakeChatQwen:
            def __init__(self, **kwargs):
                fake_chatqwen.append(kwargs)

        original_langchain_qwq = sys.modules.get("langchain_qwq")
        sys.modules["langchain_qwq"] = types.SimpleNamespace(ChatQwen=FakeChatQwen)
        try:
            if "core.llm_factory" in sys.modules:
                del sys.modules["core.llm_factory"]
            from core.llm_factory import LLMFactory

            with patch("core.llm_factory.create_llm_http_client", return_value="sync-client"), patch(
                "core.llm_factory.create_llm_async_http_client", return_value="async-client"
            ):
                LLMFactory.create_chat_model(streaming=False)
        finally:
            if original_langchain_qwq is None:
                sys.modules.pop("langchain_qwq", None)
            else:
                sys.modules["langchain_qwq"] = original_langchain_qwq
            sys.modules.pop("core.llm_factory", None)

        self.assertEqual(len(fake_chatqwen), 1)
        kwargs = fake_chatqwen[0]
        self.assertEqual(kwargs["http_client"], "sync-client")
        self.assertEqual(kwargs["http_async_client"], "async-client")
        self.assertFalse(kwargs["streaming"])


if __name__ == "__main__":
    unittest.main()
