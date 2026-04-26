import traceback

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import before_model
from langchain_core.messages import RemoveMessage, SystemMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from loguru import logger

from agents.Base_agent_service import BaseAgentService
from settings.config import config
from tools import get_current_time, summary_message, web_search


@before_model
def trim_messages_middleware(state: AgentState, runtime: Runtime) -> dict[str, object] | None:
    del runtime

    messages = state["messages"]
    if len(messages) <= config.SUMMARY_TRIGGER:
        logger.info("消息裁剪完成，无需裁剪")
        return None

    first_msg = messages[0] if messages and isinstance(messages[0], SystemMessage) else None
    if first_msg:
        old_messages = messages[1:-config.SUMMARY_KEEP_LAST]
        recent_messages = messages[-config.SUMMARY_KEEP_LAST:]
    else:
        old_messages = messages[:-config.SUMMARY_KEEP_LAST]
        recent_messages = messages[-config.SUMMARY_KEEP_LAST:]

    summary = summary_message(old_messages)
    new_messages = []
    if first_msg:
        new_messages.append(first_msg)
    new_messages.append(summary)
    new_messages.extend(recent_messages)

    logger.info("消息裁剪完成，{} 条变成 {} 条", len(messages), len(new_messages))
    return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *new_messages]}


class QuickAgentService(BaseAgentService):
    """
    quick agent 只做轻量问答。

    智能问答入口不连接知识库，避免普通聊天触发 embedding、
    Milvus 和 rerank。文件问答入口继续由 file/deep agent 负责 RAG。
    """
    context_mode = "quick"
    context_top_k = 6
    context_evidence_top_k = 4
    context_max_history_turns = 4
    context_max_evidence_items = 4
    context_max_chars = 6000

    def get_system_prompt_file(self) -> str:
        return "quick_agent_system.txt"

    def _retrieve_context_documents(self, query: str, top_k: int):
        del query, top_k
        return []

    def build_agent(self):
        return create_agent(
            self.model,
            tools=[get_current_time, web_search],
            system_prompt=self.system_prompt,
            #middleware=[trim_messages_middleware],
        )


quick_agent_service = QuickAgentService(streaming=True)
