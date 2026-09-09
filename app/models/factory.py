from langchain_qwq import ChatQwen
import os

from core.http_client_factory import create_llm_async_http_client, create_llm_http_client
from pydantic import SecretStr
from settings.config import config


class QwenModel():
    """ChatQwen 工厂。

    ChatQwen 继承自 BaseChatOpenAI，本质是 OpenAI 兼容客户端：
    切换供应商只需更换 base_url / api_key / model（DashScope/DeepSeek/Kimi/OpenAI/智谱/Ollama…）。
    每次 init_model 都从 llm_config_service 读取最新配置，支持页面改配置后热生效。
    """

    def __init__(self) -> None:
        # 兼容字段（部分工具/日志直接读取）；真实实例化以 llm_config_service 为准
        self.api_key = config.DASHSCOPE_API_KEY
        self.model_name = config.dashscope_model
        self.BASE_URL = config.DASHSCOPE_API_BASE
        # embedding/rerank 仍用 DashScope，保留 env 供其读取
        if self.api_key:
            os.environ["DASHSCOPE_API_KEY"] = self.api_key
            os.environ.setdefault("OPENAI_API_KEY", self.api_key)
        if self.BASE_URL:
            os.environ["DASHSCOPE_API_BASE"] = self.BASE_URL

    def init_model(self, steram: bool, model: str | None = None, temperature: float = 0.7):
        """创建 ChatQwen。

        model 显式传入时覆写默认模型（模型路由用 qwen-turbo 等）；
        否则用配置服务里当前激活的模型。api_key / base_url 始终取最新配置。
        """
        from services.llm_config_service import llm_config_service

        params = llm_config_service.get_active_params()
        use_model = model or params["model"]
        return ChatQwen(
            model=use_model,
            api_key=SecretStr(params["api_key"] or "not-configured"),
            base_url=params["base_url"],
            temperature=temperature,
            streaming=steram,
            http_client=create_llm_http_client(),
            http_async_client=create_llm_async_http_client(),
        )

qwen_model = QwenModel()
