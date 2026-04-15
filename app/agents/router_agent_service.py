import json
import re
import traceback
from typing import Any, AsyncGenerator, Literal

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel, Field

from agents.Base_agent_service import BaseAgentService
from utils.rag_utils import rag_utils_service


class RouterDecision(BaseModel):
    route: Literal["quick", "deep"]
    reason: str = Field(..., description="简短说明为什么这样路由")


class RouterAgentService(BaseAgentService):
    
    def __init__(self, streaming: bool = False):
        super().__init__(streaming=streaming)

        '''# Router 不需要太长的上下文，只保留最近历史和少量证据即可。
        # 这里用 ContextBuilder 先把“历史 + 检索结果”整理好，
        # 再交给 router agent 判断应该走 quick 还是 deep。
        self.context_builder = ContextBuilder(
            history_loader=get_history,
            knowledge_retriever=self._retrieve_context_documents,
            parent_chunk_retriever=None,
            rerank_fn=None,
            notes_loader=get_notes,
            config=ContextConfig(
                max_tokens=3000,
                reserve_ratio=0.2,
                min_relevance=0.1,
                enable_compression=True,
                recency_weight=0.3,
                relevance_weight=0.7,
                max_history_messages=12,
                max_history_turns=4,
                max_evidence_items=4,
                max_chars=6000,

            ),
        )'''


    
    def _retrieve_context_documents(self, query: str, top_k: int):
        """
        给 ContextBuilder 用的轻量检索适配器。

        这里不返回完整的 RAG 结构，只返回文档列表。
        ContextBuilder 会把这些文档再包装成上下文证据。
        """
        retrieved = rag_utils_service.retrieve_documents(query=query, top_k=top_k)
        return retrieved.get("docs", [])

    def _build_routing_context(self, question: str, session_id: str) -> str:
        """
        构建 router 用的上下文文本。

        失败时不要让路由中断，直接退回到原始问题，
        这样 router 至少还能继续工作。
        """
        try:
            bundle = self.context_builder.build(
                question=question,
                session_id=session_id,
                mode="router",
                top_k=4,
                evidence_top_k=4,
            )

            logger.info(
                "RouterAgent context bundle built, hints={}, trace={}",
                bundle.routing_hints,
                bundle.trace,
            )
            return bundle.final_context

        except Exception as exc:
            logger.warning("RouterAgent context build failed, fallback to raw question: {}", exc)
            return question

    
    def get_system_prompt_file(self) -> str:
        return "router_agent_system.txt"

    def build_agent(self):
        return create_agent(
            self.model,
            system_prompt=self.system_prompt,
        )

    def _simple_route_rule(self, question: str) -> RouterDecision | None:
        q = question.strip()
        deep_keywords = ["对比", "比较", "分析", "深度", "详细", "系统", "方案", "设计", "复现", "多篇", "多步", "工作流", "流程", "研究", "综述", "结构化", "论文对比"]
        quick_keywords = ["是什么", "什么意思", "解释一下", "总结一下", "快速", "简要", "简单说", "帮我看", "查一下", "有没有", "能不能"]

        if any(keyword in q for keyword in deep_keywords):
            return RouterDecision(route="deep", reason="问题涉及分析、对比或结构化任务，适合 deep_agent。")

        if len(q) <= 24 and any(keyword in q for keyword in quick_keywords):
            return RouterDecision(route="quick", reason="问题较短且偏单点问答，适合 quick_agent。")

        return None

    def _extract_json(self, text: str) -> RouterDecision:
        content = text.strip()

        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        match = re.search(r"\{.*\}", content, re.S)
        if match:
            content = match.group(0)

        data = json.loads(content)
        return RouterDecision(**data)

    async def _initialize_agent(self):
        await super()._initialize_agent()

    def _get_child_agents(self):
        from agents.deep_agent_service import deep_agent_service
        from agents.quick_agent_service import quick_agent_service

        return quick_agent_service, deep_agent_service


    async def route_query(self, question: str, session_id: str) -> RouterDecision:
        rule_decision = self._simple_route_rule(question)
        if rule_decision is not None:
            logger.info(
                "RouterAgent 规则路由完成，会话: {}，route: {}，reason: {}",
                session_id,
                rule_decision.route,
                rule_decision.reason,
            )
            return rule_decision

        await self._initialize_agent()
        try:
            logger.info("RouterAgent 开始 LLM 路由判断，会话: {}", session_id)

            # 先把历史和检索证据压成一段轻量上下文，
            # 这样 router 不会只看“裸问题”，而是看“问题 + 证据 + 历史”。
            routing_context = self._build_routing_context(question, session_id)

            # router agent 只吃一段系统上下文 + 当前问题。
            # 这里不要再手工把整段历史直接塞进去，
            # 因为我们已经通过 ContextBuilder 做过一次整理了。
            messages = [
                SystemMessage(content=routing_context),
                HumanMessage(content=question),
            ]

            result = await self.agent.ainvoke(input={"messages": messages})
            messages_result = result.get("messages", [])
            if not messages_result:
                return RouterDecision(route="deep", reason="路由结果为空，默认走 deep_agent。")

            last_message = messages_result[-1]
            content = last_message.content if hasattr(last_message, "content") else str(last_message)

            try:
                decision = self._extract_json(content)
            except Exception:
                logger.warning("RouterAgent JSON 解析失败，默认走 deep_agent，会话: {}", session_id)
                return RouterDecision(route="deep", reason="路由输出无法解析，默认走 deep_agent。")

            if decision.route not in ("quick", "deep"):
                return RouterDecision(route="deep", reason="路由结果不合法，默认走 deep_agent。")

            logger.info(
                "RouterAgent 路由完成，会话: {}，route: {}，reason: {}",
                session_id,
                decision.route,
                decision.reason,
            )
            return decision

        except Exception as exc:
            logger.error("RouterAgent 路由失败，会话: {}，错误: {}", session_id, exc)
            logger.error("异常堆栈:\n{}", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            return RouterDecision(route="deep", reason="路由过程异常，默认走 deep_agent。")

    
    async def deep_query(self, question: str, session_id: str) -> str:
        _, deep_agent_service = self._get_child_agents()
        return await deep_agent_service.query(question, session_id)

    async def deep_query_stream(self, question: str, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
        _, deep_agent_service = self._get_child_agents()
        async for chunk in deep_agent_service.query_stream(question, session_id):
            yield chunk

    async def query(self, question: str, session_id: str) -> str:
        decision = await self.route_query(question, session_id)
        quick_agent_service, deep_agent_service = self._get_child_agents()

        if decision.route == "deep":
            logger.info("RouterAgent 分发到 deep_agent，会话: {}", session_id)
            return await deep_agent_service.query(question, session_id)

        logger.info("RouterAgent 分发到 quick_agent，会话: {}", session_id)
        return await quick_agent_service.query(question, session_id)

    async def query_stream(self, question: str, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
        decision = await self.route_query(question, session_id)
        quick_agent_service, deep_agent_service = self._get_child_agents()

        if decision.route == "deep":
            logger.info("RouterAgent 流式分发到 deep_agent，会话: {}", session_id)
            async for chunk in deep_agent_service.query_stream(question, session_id):
                yield chunk
            return

        logger.info("RouterAgent 流式分发到 quick_agent，会话: {}", session_id)
        async for chunk in quick_agent_service.query_stream(question, session_id):
            yield chunk


agent_service = RouterAgentService(streaming=True)

