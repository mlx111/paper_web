from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.store.memory import InMemoryStore
from loguru import logger

from context.builder import ContextBuilder
from context.context_config import ContextConfig
from models.factory import qwen_model
from settings.config import config
from utils.history import get_history
from utils.rag_utils import rag_utils_service


class BaseAgentService(ABC):
    """
    所有 agent 的公共基类。

    这一版的核心目标是：
    - 统一上下文构建入口
    - 不让 quick / deep / router 各自拼上下文
    - notes 作为可选长期记忆层，由子类决定是否接入
    """

    context_mode: str = "deep"
    context_top_k: int = 8
    context_evidence_top_k: int = 6
    context_max_tokens: int = 3000
    context_reserve_ratio: float = 0.2
    context_min_relevance: float = 0.1
    context_enable_compression: bool = True
    context_recency_weight: float = 0.3
    context_relevance_weight: float = 0.7
    context_max_history_messages: int = 12
    context_max_history_turns: int = 6
    context_max_evidence_items: int = 6
    context_max_chars: int = 12000

    def __init__(self, streaming: bool = False):
        self.model_name = config.rag_model
        self.streaming = streaming
        self.prompt_dir = Path(__file__).resolve().parent.parent / "prompt"
        self.system_prompt_file = self.get_system_prompt_file()
        self.system_prompt = self._build_system_prompt()

        self.store = InMemoryStore()
        self.model = qwen_model.init_model(streaming)

        self.context_config = self._build_context_config()
        self.context_builder = self._build_context_builder()

        self.agent = None
        self._agent_initialized = False

        logger.info(
            "{} 服务初始化完成，模型: {}，流式: {}，上下文模式: {}",
            self.__class__.__name__,
            self.model_name,
            streaming,
            self.context_mode,
        )

    @abstractmethod
    def get_system_prompt_file(self) -> str:
        raise NotImplementedError

    def _load_prompt_file(self, filename: str, default: str = "") -> str:
        try:
            prompt_path = self.prompt_dir / filename
            content = prompt_path.read_text(encoding="utf-8").strip()
            logger.info("提示词文件读取完成: {}", prompt_path.as_posix())
            return content
        except Exception as exc:
            logger.error("提示词文件读取失败: {}", exc)
            return default

    def _build_system_prompt(self) -> str:
        default_prompt = (
            "你是一个专业的 AI 助手，能够使用多种工具来帮助用户解决问题。"
            "请优先基于工具返回结果回答，回答要准确、简洁、诚实。"
        )
        prompt = self._load_prompt_file(self.system_prompt_file, default=default_prompt)
        logger.info("基础系统提示词构建完成")
        return prompt

    def _build_context_config(self) -> ContextConfig:
        """
        把上下文预算统一收敛到 ContextConfig。

        子类只需要改类属性，不需要自己拼配置。
        """
        return ContextConfig(
            max_tokens=self.context_max_tokens,
            reserve_ratio=self.context_reserve_ratio,
            min_relevance=self.context_min_relevance,
            enable_compression=self.context_enable_compression,
            recency_weight=self.context_recency_weight,
            relevance_weight=self.context_relevance_weight,
            max_history_messages=self.context_max_history_messages,
            max_history_turns=self.context_max_history_turns,
            max_evidence_items=self.context_max_evidence_items,
            max_chars=self.context_max_chars,
        )

    def _retrieve_context_documents(self, query: str, top_k: int):
        """
        给 ContextBuilder 用的检索适配器。

        这里复用现有 RAG 检索结果，让上下文层只负责组装，不负责重写检索。
        """
        retrieved = rag_utils_service.retrieve_documents(query=query, top_k=top_k)
        return retrieved.get("docs", [])

    def _retrieve_context_notes(self, session_id: str):
        """
        给 ContextBuilder 用的 notes 读取适配器。

        默认不接 notes。
        如果某个子类需要 notes，可以重写这个方法。
        """
        return None

    def _build_context_builder(self) -> ContextBuilder:
        """
        统一创建 ContextBuilder。

        这样 quick / deep / router 都可以共用同一套上下文工程。
        """
        return ContextBuilder(
            history_loader=get_history,
            knowledge_retriever=self._retrieve_context_documents,
            parent_chunk_retriever=None,
            notes_loader=self._retrieve_context_notes,
            rerank_fn=None,
            config=self.context_config,
        )

    def _history(self, session_id: str):
        return get_history(session_id)

    def _history_messages(self, session_id: str):
        return [msg for msg in self._history(session_id).messages if not isinstance(msg, SystemMessage)]

    def _save_turn(self, session_id: str, question: str, answer: str) -> None:
        history = self._history(session_id)
        payload = [HumanMessage(content=question)]
        if answer:
            payload.append(AIMessage(content=answer))
        history.add_messages(payload)

    def build_context_bundle(self, question: str, session_id: str):
        """
        统一构建上下文包。
        """
        return self.context_builder.build(
            question=question,
            session_id=session_id,
            mode=self.context_mode,
            top_k=self.context_top_k,
            evidence_top_k=self.context_evidence_top_k,
        )

    def _build_messages(self, question: str, session_id: str):
        """
        把最终要喂给模型的消息统一组装起来。
        """
        bundle = self.build_context_bundle(question, session_id)

        messages = []
        if bundle.final_context:
            messages.append(SystemMessage(content=bundle.final_context))
        messages.append(HumanMessage(content=question))
        return messages, bundle

    @abstractmethod
    def build_agent(self):
        raise NotImplementedError

    async def _initialize_agent(self):
        if self._agent_initialized:
            logger.info("{} 已初始化，直接复用", self.__class__.__name__)
            return

        try:
            self.agent = self.build_agent()
            self._agent_initialized = True
            logger.info("{} 创建完成", self.__class__.__name__)
        except Exception as exc:
            logger.error("{} 创建失败: {}", self.__class__.__name__, exc)
            raise


    async def query(self, question: str, session_id: str) -> str:
        try:
            await self._initialize_agent()
            logger.info("{} 对话开始，会话: {}", self.__class__.__name__, session_id)

            messages, bundle = self._build_messages(question, session_id)
            logger.info(
                "{} 上下文构建完成，会话: {}，mode: {}，hints: {}",
                self.__class__.__name__,
                session_id,
                bundle.mode,
                bundle.routing_hints,
            )

            result = await self.agent.ainvoke(input={"messages": messages})

            messages_result = result.get("messages", [])
            if not messages_result:
                logger.info("{} 对话完成，但返回为空，会话: {}", self.__class__.__name__, session_id)
                return ""

            last_message = messages_result[-1]
            answer = last_message.content if hasattr(last_message, "content") else str(last_message)

            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                tool_names = [tool_call.get("name", "unknown") for tool_call in last_message.tool_calls]
                logger.info("{} 工具调用完成，会话: {}，工具: {}", self.__class__.__name__, session_id, tool_names)

            if answer:
                self._save_turn(session_id, question, answer)

            logger.info("{} 对话完成，会话: {}", self.__class__.__name__, session_id)
            return answer
        except Exception as exc:
            logger.error("{} 对话失败，会话: {}，错误: {}", self.__class__.__name__, session_id, exc)
            logger.error("异常堆栈:\n{}", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            if hasattr(exc, "exceptions"):
                for index, sub in enumerate(exc.exceptions):
                    logger.error("子异常{}:\n{}", index, "".join(traceback.format_exception(type(sub), sub, sub.__traceback__)))
            raise

    async def query_stream(self, question: str, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
        try:
            await self._initialize_agent()
            logger.info("{} 流式对话开始，会话: {}", self.__class__.__name__, session_id)

            messages, bundle = self._build_messages(question, session_id)
            logger.info(
                "{} 上下文构建完成，会话: {}，mode: {}，hints: {}",
                self.__class__.__name__,
                session_id,
                bundle.mode,
                bundle.routing_hints,
            )

            answer_parts: list[str] = []

            async for token, metadata in self.agent.astream(input={"messages": messages}, stream_mode="messages"):
                node_name = metadata.get("langgraph_node", "unknown") if isinstance(metadata, dict) else "unknown"
                message_type = type(token).__name__

                if message_type in ("AIMessage", "AIMessageChunk"):
                    content_blocks = getattr(token, "content_blocks", None)
                    if content_blocks and isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_content = block.get("text", "")
                                if text_content:
                                    answer_parts.append(text_content)
                                    yield {"type": "content", "data": text_content, "node": node_name}

                elif message_type in ("ToolCallMessage", "ToolCallMessageChunk"):
                    tool_calls = getattr(token, "tool_calls", None)
                    if tool_calls and isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            yield {
                                "type": "tool_call",
                                "data": {
                                    "tool_name": tool_call.get("name", "unknown"),
                                    "arguments": tool_call.get("arguments", {}),
                                },
                                "node": node_name,
                            }

            final_answer = "".join(answer_parts).strip()
            if final_answer:
                self._save_turn(session_id, question, final_answer)

            logger.info("{} 流式对话完成，会话: {}", self.__class__.__name__, session_id)
            yield {"type": "complete"}
        except Exception as exc:
            logger.error("{} 流式对话失败，会话: {}，错误: {}", self.__class__.__name__, session_id, exc)
            logger.error("异常堆栈:\n{}", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            if hasattr(exc, "exceptions"):
                for index, sub in enumerate(exc.exceptions):
                    logger.error("子异常{}:\n{}", index, "".join(traceback.format_exception(type(sub), sub, sub.__traceback__)))
            raise

    def get_session_history(self, session_id: str) -> list:
        try:
            messages = self._history_messages(session_id)
            history = []
            for msg in messages:
                if isinstance(msg, HumanMessage):
                    role = "user"
                else:
                    role = "assistant"
                content = msg.content if hasattr(msg, "content") else str(msg)
                timestamp = getattr(msg, "timestamp", None)
                if not timestamp:
                    from datetime import datetime

                    timestamp = datetime.now().isoformat()
                history.append({"role": role, "content": content, "timestamp": timestamp})

            logger.info("{} 会话历史读取完成，会话: {}，消息数: {}", self.__class__.__name__, session_id, len(history))
            return history
        except Exception as exc:
            logger.error("{} 会话历史读取失败，会话: {}，错误: {}", self.__class__.__name__, session_id, exc)
            return []

    def clear_session(self, session_id: str) -> bool:
        try:
            self._history(session_id).clear()
            logger.info("{} 会话清理完成，会话: {}", self.__class__.__name__, session_id)
            return True
        except Exception as exc:
            logger.error("{} 会话清理失败，会话: {}，错误: {}", self.__class__.__name__, session_id, exc)
            return False

    async def cleanup(self):
        try:
            logger.info("{} 资源清理完成", self.__class__.__name__)
        except Exception as exc:
            logger.error("{} 资源清理失败: {}", self.__class__.__name__, exc)
