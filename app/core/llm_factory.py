"""Legacy entry point for explicit OpenAI-compatible model parameters."""

from core.http_client_factory import create_llm_async_http_client, create_llm_http_client
from models.factory import UniversalChatOpenAI, UniversalModelFactory
from pydantic import SecretStr
from settings.config import config


class LLMFactory:
    """LLM 工厂类 - 使用 OpenAI 兼容模式"""

    # 阿里云 DashScope OpenAI 兼容模式 URL
    DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @staticmethod
    def create_chat_model(
        model: str | None = None,
        temperature: float = 0.7,
        streaming: bool = True,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> UniversalChatOpenAI:
        model = model or config.dashscope_model
        base_url = base_url or LLMFactory.DASHSCOPE_BASE_URL
        api_key = api_key or config.DASHSCOPE_API_KEY

        llm = UniversalChatOpenAI(
            model=model,
            **UniversalModelFactory._temperature_params(model, temperature),
            streaming=streaming,
            base_url=base_url,
            api_key=SecretStr(api_key),
            provider="dashscope" if "dashscope" in base_url else "custom",
            preserve_reasoning_content="dashscope" in base_url or "deepseek" in base_url,
            use_responses_api=False,
            http_client=create_llm_http_client(),
            http_async_client=create_llm_async_http_client(),
        )
        return llm

# 全局 LLM 工厂实例
llm_factory = LLMFactory()
