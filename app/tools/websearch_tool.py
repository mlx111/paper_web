from langchain.tools import tool
from loguru import logger

from services.web_search_service import get_web_search_service


@tool(
    name_or_callable="web_search",
    description="当需要进行网络搜索时，调用该工具。传入参数包括：query（搜索关键词），count（返回结果数量，默认 5）。"
    "支持多个搜索提供商自动切换，优先使用 Tavily，不可用时自动降级到备用服务。",
)
def web_search(query: str, count: int = 5):
    """Multi-provider web search with automatic fallback."""
    try:
        service = get_web_search_service()
        result = service.search(query, count)
        if "error" in result:
            logger.error(f"web_search failed: {result['error']}")
        return result
    except Exception as e:
        logger.error(f"web_search tool error: {e}")
        return {"error": f"联网搜索失败: {str(e)}"}
