import sys
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

    def test_universal_model_init_passes_proxy_bypass_clients(self):
        created_models = []

        class FakeModel:
            def __init__(self, **kwargs):
                created_models.append(kwargs)

        from models.factory import UniversalModelFactory

        with patch("models.factory.UniversalChatOpenAI", FakeModel), patch(
            "models.factory.create_llm_http_client", return_value="sync-client"
        ), patch("models.factory.create_llm_async_http_client", return_value="async-client"), patch(
            "services.llm_config_service.llm_config_service.get_active_params",
            return_value={"provider": "deepseek", "model": "test-model", "base_url": "https://example.test/v1", "api_key": "test"},
        ):
            UniversalModelFactory().init_model(True)

        self.assertEqual(len(created_models), 1)
        kwargs = created_models[0]
        self.assertEqual(kwargs["http_client"], "sync-client")
        self.assertEqual(kwargs["http_async_client"], "async-client")
        self.assertTrue(kwargs["streaming"])

    def test_llm_factory_passes_proxy_bypass_clients(self):
        created_models = []

        class FakeModel:
            def __init__(self, **kwargs):
                created_models.append(kwargs)

        from core.llm_factory import LLMFactory

        with patch("core.llm_factory.UniversalChatOpenAI", FakeModel), patch(
            "core.llm_factory.create_llm_http_client", return_value="sync-client"
        ), patch("core.llm_factory.create_llm_async_http_client", return_value="async-client"):
            LLMFactory.create_chat_model(streaming=False)

        self.assertEqual(len(created_models), 1)
        kwargs = created_models[0]
        self.assertEqual(kwargs["http_client"], "sync-client")
        self.assertEqual(kwargs["http_async_client"], "async-client")
        self.assertFalse(kwargs["streaming"])


if __name__ == "__main__":
    unittest.main()
