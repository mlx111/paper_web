"""大模型配置接口：页面查看/修改当前激活的 LLM（供应商、模型名、API Key、接口地址）。

- GET  /llm-config        获取当前配置（API Key 脱敏，只回是否已配置 + 掩码）
- PUT  /llm-config        更新配置（api_key 留空表示不修改），保存后热重载所有 agent
- POST /llm-config/test   测试连通性（可用表单里尚未保存的值）
"""

from fastapi import APIRouter
from pydantic import BaseModel
from loguru import logger

from services.llm_config_service import llm_config_service

router = APIRouter(prefix="/llm-config", tags=["llm-config"])


class LLMConfigBody(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


@router.get("")
def get_llm_config():
    return llm_config_service.get_public_config()


@router.put("")
def update_llm_config(body: LLMConfigBody):
    result = llm_config_service.update_config(
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
        api_key=body.api_key,
    )
    _reset_all_agents()
    return result


@router.post("/test")
def test_llm_config(body: LLMConfigBody):
    return llm_config_service.test_connection(
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
        api_key=body.api_key,
    )


@router.post("/models")
def fetch_llm_models(body: LLMConfigBody):
    """根据当前（或表单里的）供应商 / Base URL / API Key 拉取可用模型列表。"""
    return llm_config_service.fetch_models(
        provider=body.provider,
        base_url=body.base_url,
        api_key=body.api_key,
    )


def _reset_all_agents() -> None:
    """重置所有全局 agent 实例，使其下次请求时用最新 LLM 配置重建（热生效，不重启容器）。"""
    try:
        from agents.quick_agent_service import quick_agent_service
        from agents.deep_agent_service import deep_agent_service
        from agents.multi_agent_service import multi_agent_service
        from agents.file_agent_service import file_agent_service
        from evaluation import dispatcher

        for svc in (quick_agent_service, deep_agent_service, multi_agent_service, file_agent_service):
            svc.reset_agent()
        # 模型路由的 simple agent 是懒加载缓存，置空后下次重建
        dispatcher._simple_quick_agent = None
        logger.info("所有 agent 已重置，下一轮对话将使用新的 LLM 配置")
    except Exception as exc:
        logger.warning("重置 agent 失败（不影响配置保存）：{}", exc)
