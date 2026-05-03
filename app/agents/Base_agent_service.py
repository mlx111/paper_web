from __future__ import annotations

import re
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
from utils.notes import save_high_value_note, get_memory_writer, select_relevant_memories
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

    def __init__(self, streaming: bool = False, history_loader=None):
        self.model_name = config.rag_model
        self.streaming = streaming
        self.prompt_dir = Path(__file__).resolve().parent.parent / "prompt"
        self.system_prompt_file = self.get_system_prompt_file()
        self.system_prompt = self._build_system_prompt()

        self.history_loader = history_loader or get_history
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
        给 ContextBuilder 用的 notes 读取适配器（旧系统）。

        默认不接 notes。
        如果某个子类需要 notes，可以重写这个方法。
        """
        return None

    def _retrieve_context_memories(self, question: str, limit: int) -> list[dict[str, Any]]:
        """
        给 ContextBuilder 用的结构化记忆加载适配器（新系统）。

        使用语义筛选，只加载与当前问题相关的记忆。
        """
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Running in async context — use sync fallback
                from utils.notes import get_memory_selector
                selector = get_memory_selector()
                entries = selector.select_sync(question, max_results=limit)
                return [
                    {
                        "title": e.name,
                        "content": e.content,
                        "kind": e.type.value,
                        "importance": 0.9,
                        "tags": ["memory", e.type.value],
                        "metadata": {
                            "memory_type": e.type.value,
                            "source_session": e.source_session_id,
                        },
                    }
                    for e in entries
                ]
            else:
                # Synchronous context — run async
                import asyncio as _asyncio
                result = _asyncio.run(select_relevant_memories(question, max_results=limit))
                return result
        except Exception:
            return []

    def _build_context_builder(self) -> ContextBuilder:
        """
        统一创建 ContextBuilder。

        现在同时接入旧 notes 系统和新结构化记忆系统。
        """
        memory_loader = None
        if self.context_config.enable_structured_memory:
            memory_loader = self._retrieve_context_memories

        return ContextBuilder(
            history_loader=self.history_loader,
            knowledge_retriever=self._retrieve_context_documents,
            parent_chunk_retriever=None,
            notes_loader=self._retrieve_context_notes,
            memory_loader=memory_loader,
            rerank_fn=None,
            config=self.context_config,
        )

    def _history(self, session_id: str):
        return self.history_loader(session_id)

    def _history_messages(self, session_id: str):
        return [msg for msg in self._history(session_id).messages if not isinstance(msg, SystemMessage)]

    def _save_turn(self, session_id: str, question: str, answer: str) -> None:
        history = self._history(session_id)
        payload = [HumanMessage(content=question)]
        if answer:
            payload.append(AIMessage(content=answer))
        history.add_messages(payload)

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    def _shorten_text(self, value: str, limit: int) -> str:
        text = self._normalize_text(value)
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    def _extract_memory_note(self, session_id: str, question: str, answer: str) -> dict[str, Any] | None:
        """
        Extract a conservative memory candidate from a completed answer.

        Only high-signal content should survive this gate.
        """
        question_text = self._normalize_text(question)
        answer_text = self._normalize_text(answer)
        if not answer_text:
            return None

        combined = f"{question_text} {answer_text}".lower()

        rule_set: list[tuple[str, tuple[str, ...], float]] = [
            (
                "constraint",
                (
                    "must not",
                    "must ",
                    "never",
                    "cannot",
                    "can't",
                    "avoid",
                    "limit",
                    "constraint",
                    "required",
                    "require",
                    "do not",
                    "don't",
                    "必须",
                    "务必",
                    "一定要",
                    "不能",
                    "不要",
                    "禁止",
                    "避免",
                    "限制",
                    "约束",
                    "要求",
                ),
                0.92,
            ),
            (
                "decision",
                (
                    "recommend",
                    "should",
                    "best",
                    "choose",
                    "decide",
                    "decision",
                    "prefer",
                    "建议",
                    "推荐",
                    "应该",
                    "最好",
                    "选择",
                    "决定",
                ),
                0.88,
            ),
            (
                "preference",
                (
                    "prefer",
                    "like",
                    "favorite",
                    "favourite",
                    "want",
                    "rather",
                    "偏好",
                    "喜欢",
                    "希望",
                    "想要",
                    "倾向",
                ),
                0.84,
            ),
            (
                "blocker",
                (
                    "blocked",
                    "problem",
                    "issue",
                    "risk",
                    "bug",
                    "failure",
                    "error",
                    "问题",
                    "风险",
                    "错误",
                    "失败",
                    "缺陷",
                    "阻塞",
                ),
                0.8,
            ),
            (
                "summary",
                (
                    "in summary",
                    "to sum up",
                    "overall",
                    "key point",
                    "key points",
                    "summary",
                    "总结",
                    "概括",
                    "要点",
                    "重点",
                    "结论",
                ),
                0.76,
            ),
            (
                "memory",
                (
                    "remember",
                    "keep in mind",
                    "note that",
                    "long-term",
                    "for later",
                    "记住",
                    "记忆",
                    "以后",
                    "后续",
                    "长期",
                    "留意",
                ),
                0.82,
            ),
        ]

        kind = None
        importance = 0.0
        for candidate_kind, patterns, candidate_importance in rule_set:
            if any(pattern in combined for pattern in patterns):
                kind = candidate_kind
                importance = candidate_importance
                break

        if kind is None:
            if len(answer_text) >= 220 and any(
                token in combined
                for token in (
                    "important",
                    "key",
                    "crucial",
                    "stable",
                    "always",
                    "must",
                    "重要",
                    "关键",
                    "核心",
                    "稳定",
                    "总是",
                    "必须",
                )
            ):
                kind = "summary"
                importance = 0.7
            else:
                return None

        title_source = question_text or answer_text
        title = f"{kind}: {self._shorten_text(title_source, 72)}"
        content = self._shorten_text(
            f"Question: {question_text}\nAnswer: {answer_text}",
            1200,
        )

        return {
            "title": title,
            "content": content,
            "kind": kind,
            "importance": importance,
            "tags": [kind, self.context_mode],
            "extra": {
                "source": "agent_memory",
                "session_id": session_id,
                "question_preview": self._shorten_text(question_text, 160),
                "answer_preview": self._shorten_text(answer_text, 240),
                "reason": kind,
            },
        }

    def _persist_memory(self, session_id: str, question: str, answer: str) -> None:
        """
        Persist a high-value memory note when the response looks reusable.

        Saves to both:
        1. Legacy NoteService (app/data/notes/)
        2. New structured Memory system (app/data/memory/)
        """
        if not answer:
            return

        memory_note = self._extract_memory_note(session_id, question, answer)
        if memory_note is None:
            return

        # Legacy system
        saved = save_high_value_note(
            session_id=session_id,
            title=memory_note["title"],
            content=memory_note["content"],
            tags=memory_note["tags"],
            kind=memory_note["kind"],
            importance=memory_note["importance"],
            source="agent_memory",
            extra=memory_note["extra"],
        )

        # New structured memory system
        try:
            from utils.notes import save_memory_from_turn
            mem_result = save_memory_from_turn(
                user_message=question,
                assistant_response=answer,
                session_id=session_id,
            )
            if mem_result:
                logger.info(
                    "{} 结构化记忆写入完成，会话: {}，type: {}，title: {}",
                    self.__class__.__name__,
                    session_id,
                    mem_result["type"],
                    mem_result["title"],
                )
        except Exception:
            pass  # New system failure is non-fatal

        if saved is not None:
            logger.info(
                "{} 记忆写入完成，会话: {}，kind: {}，title: {}",
                self.__class__.__name__,
                session_id,
                memory_note["kind"],
                memory_note["title"],
            )

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

    @staticmethod
    def _pre_compress_messages(messages: list, config_obj: Any = None) -> list:
        """
        Hermes-style 消息级压缩钩子。

        当消息列表超过上下文窗口 50% 时触发四阶段压缩。
        当前 base agent 消息列表极短（2 条），实际不会触发；
        此钩子为研究流程等长消息场景保留统一入口。
        """
        if not config_obj:
            config_obj = ContextConfig()

        if not getattr(config_obj, "enable_hermes_compression", False):
            return messages

        # Lazy import to avoid circular dependency
        from app.services.context_compressor_service import (
            CompressorConfig,
            ContextCompressorService,
        )

        comp_config = CompressorConfig(
            context_window_tokens=getattr(config_obj, "context_window_tokens", 32000),
            compression_threshold_ratio=getattr(config_obj, "compression_trigger_ratio", 0.5),
            head_protect_messages=getattr(config_obj, "head_protect_messages", 3),
            tail_token_budget=getattr(config_obj, "tail_token_budget", 20000),
            llm_enabled=getattr(config_obj, "summary_llm_enabled", True),
            summarize_prompt_limit=getattr(config_obj, "summary_prompt_limit", 8000),
            anti_thrash_min_savings=getattr(config_obj, "anti_thrash_min_savings", 0.1),
            anti_thrash_consecutive_limit=getattr(config_obj, "anti_thrash_consecutive_limit", 2),
        )

        compressor = ContextCompressorService(comp_config)
        result = compressor.compress_messages(messages)

        if result.was_compressed:
            logger.info(
                "消息压缩完成: {} 条 -> {} 条, 节省 {:.1%}{}",
                len(messages),
                len(result.messages),
                result.savings_ratio,
                " [THRASH]" if result.thrash_warning else "",
            )

        return result.messages

    @staticmethod
    def _extract_tool_names(messages) -> list[str]:
        tool_names: list[str] = []
        for message in messages or []:
            for tool_call in getattr(message, "tool_calls", []) or []:
                if isinstance(tool_call, dict):
                    name = tool_call.get("name") or tool_call.get("tool_name") or "unknown"
                else:
                    name = getattr(tool_call, "name", None) or getattr(tool_call, "tool_name", None) or "unknown"
                if name and name not in tool_names:
                    tool_names.append(str(name))
        return tool_names

    def _log_tool_usage(self, session_id: str, tool_names: list[str]) -> None:
        if tool_names:
            logger.info("{} 本轮调用工具，会话: {}，工具: {}", self.__class__.__name__, session_id, tool_names)
            return
        logger.info("{} 本轮未调用工具，会话: {}", self.__class__.__name__, session_id)

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
            # 加在这里
            
            result = await self.agent.ainvoke(input={"messages": messages})

            messages_result = result.get("messages", [])
            if not messages_result:
                logger.info("{} 对话完成，但返回为空，会话: {}", self.__class__.__name__, session_id)
                return ""

            last_message = messages_result[-1]
            answer = last_message.content if hasattr(last_message, "content") else str(last_message)

            self._log_tool_usage(session_id, self._extract_tool_names(messages_result))

            if answer:
                self._save_turn(session_id, question, answer)
                self._persist_memory(session_id, question, answer)

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

            # 先把上下文元信息吐给外层评估器。
            # 这样 runner 可以准确知道这次请求用了什么 context_mode，
            # 以及 context 里到底有没有 notes / history / evidence。
            yield {
                "type": "context",
                "data": {
                    "context_mode": bundle.mode,
                    "routing_hints": bundle.routing_hints,
                    "trace": bundle.trace,
                },
            }

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
                            tool_name = tool_call.get("name", "unknown")
                            logger.info(
                                "{} 流式调用工具，会话: {}，工具: {}，节点: {}",
                                self.__class__.__name__,
                                session_id,
                                tool_name,
                                node_name,
                            )
                            yield {
                                "type": "tool_call",
                                "data": {
                                    "tool_name": tool_name,
                                    "arguments": tool_call.get("arguments", {}),
                                },
                                "node": node_name,
                            }

            final_answer = "".join(answer_parts).strip()
            if final_answer:
                self._save_turn(session_id, question, final_answer)
                self._persist_memory(session_id, question, final_answer)

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
