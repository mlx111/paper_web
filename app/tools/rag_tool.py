"""Knowledge retrieval tool used by the file/deep agent."""

from textwrap import dedent
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_core.tools import tool
from loguru import logger

from settings.config import config
from utils.rag_utils import rag_utils_service


@tool(
    response_format="content_and_artifact",
    description=dedent(
        """
        从知识库中检索与用户问题相关的文档片段，用于回答论文、文档内容、
        方法解释、实验结果分析、图文资料定位等问题。

        如果检索结果中包含 <<IMAGE:xxxxxxxx>> 图片占位符，说明该位置关联了
        文档中的真实图片。回答时只能原样引用已有占位符，不能编造新占位符。

        Args:
            query: 用户的问题或检索查询。

        Returns:
            Tuple[str, List[Document]]: 格式化后的上下文文本和原始文档列表。
        """
    ),
)
def retrieve_knowledge(query: str) -> Tuple[str, List[Document]]:
    """Retrieve relevant knowledge-base documents for answering a question."""
    try:
        logger.info("知识检索工具被调用: query='{}'", query)
        result = rag_utils_service.retrieve_documents(query, top_k=config.rag_top_k)
        docs = result.get("docs", []) if isinstance(result, dict) else []
        if not docs:
            logger.warning("未检索到相关文档")
            return "没有找到相关信息。", []

        context = format_docs(docs)
        logger.info("检索到 {} 个相关文档", len(docs))
        return context, docs
    except Exception as exc:
        logger.error("知识检索工具调用失败: {}", exc)
        return f"检索知识时发生错误: {exc}", []


def format_docs(docs: List[Document]) -> str:
    """Format retrieved documents into model-readable context."""
    formatted_parts: list[str] = []

    if any("<<IMAGE:" in (doc.page_content or "") for doc in docs):
        formatted_parts.append(
            "提示：以下资料中包含图片占位符，格式为 <<IMAGE:8位十六进制字符>>。"
            "如果图片与回答直接相关，请在回答中原样保留对应占位符；"
            "只能使用资料中已出现的占位符，禁止改写或编造。"
        )

    for index, doc in enumerate(docs, 1):
        metadata = doc.metadata or {}
        source = metadata.get("_file_name") or metadata.get("filename") or "未知来源"
        page_number = metadata.get("page_number")

        headers = [
            str(metadata[key]).strip()
            for key in ("h1", "h2", "h3")
            if metadata.get(key)
        ]
        header_text = " > ".join(headers)

        formatted = [f"【参考资料 {index}】", f"来源: {source}"]
        if page_number is not None:
            formatted.append(f"页码: {page_number}")
        if header_text:
            formatted.append(f"标题: {header_text}")
        formatted.append(f"内容:\n{doc.page_content}")

        formatted_parts.append("\n".join(formatted))

    return "\n\n".join(formatted_parts)
