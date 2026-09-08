from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend, StoreBackend
from langchain_core.messages import SystemMessage

from agents.Base_agent_service import BaseAgentService
from tools import (
    academic_search_papers,
    build_citation_pool,
    extract_document_text,
    get_current_time,
    get_paper_abstract,
    get_paper_bibtex,
    retrieve_knowledge,
    review_paper_quality,
    web_search,
)
from utils.notes import get_notes


class DeepAgentService(BaseAgentService):
    """
    deep agent 负责复杂分析和多步任务。

    它同样复用 BaseAgentService 的 ContextBuilder，
    不再自己拼历史或检索上下文。
    """
    context_mode = "deep"
    context_top_k = 8
    context_evidence_top_k = 6
    context_max_history_turns = 6
    context_max_evidence_items = 6
    context_max_chars = 12000

    def get_system_prompt_file(self) -> str:
        return "deep_agent_system.txt"
    def _retrieve_context_notes(self, session_id: str):
        """
        deep 读取结构化笔记。

        这样 notes 只在 deep 场景里参与上下文，
        quick 不会被长期记忆拖慢。
        """
        return get_notes(session_id)

    def default_tools(self) -> list:
        # 本地工具 + MCP Host 运行时动态发现的外部工具（来源标记为 mcp）
        return [
            retrieve_knowledge,
            get_current_time,
            web_search,
            academic_search_papers,
            get_paper_abstract,
            get_paper_bibtex,
            review_paper_quality,
            build_citation_pool,
            extract_document_text,
            *self._mcp_tools(),
        ]

    def _mcp_tools(self) -> list:
        """外部 MCP server 工具（由 MCP Host 在应用启动时连接并动态注册）。

        延迟导入：MCP Host 不可用/未连接时返回空列表，不影响 Agent 本身。
        Agent 是懒初始化的（首次对话才 build_agent），此时 lifespan 已完成
        MCP 连接，因此能拿到已注册的外部工具。
        """
        try:
            from services.mcp_client_service import mcp_client_service

            return mcp_client_service.get_langchain_tools()
        except Exception:
            return []

    def _get_skill_registry(self):
        registry = getattr(self, "skill_registry", None)
        if registry is not None:
            return registry

        from services.skill_registry import skill_registry

        self.skill_registry = skill_registry
        return skill_registry

    def select_skill(self, question: str) -> dict[str, Any] | None:
        """
        Select a task-level skill by trigger keywords.

        Tool is the executable layer, MCP is the protocol exposure layer, and
        Skill is the task procedure layer that constrains process and tools.
        """
        registry = self._get_skill_registry()
        matches = registry.find_by_trigger(question or "")
        if not matches:
            return None

        skill = matches[0]
        variables = {"question": question or ""}
        return {
            "name": getattr(skill, "name", ""),
            "description": getattr(skill, "description", ""),
            "body": skill.resolve_body(variables) if hasattr(skill, "resolve_body") else "",
            "enabled_tools": list(getattr(skill, "enabled_tools", []) or []),
            "disabled_tools": list(getattr(skill, "disabled_tools", []) or []),
        }

    @staticmethod
    def _tool_name(tool) -> str:
        return getattr(tool, "name", None) or getattr(tool, "__name__", "")

    def filter_tools_for_skill(self, tools: list, selected_skill: dict[str, Any] | None) -> list:
        if not selected_skill:
            return list(tools)

        enabled = set(selected_skill.get("enabled_tools") or [])
        disabled = set(selected_skill.get("disabled_tools") or [])
        if "*" in disabled:
            return []

        filtered = []
        for tool in tools:
            name = self._tool_name(tool)
            if enabled and name not in enabled:
                continue
            if name in disabled:
                continue
            filtered.append(tool)
        return filtered

    def _build_messages(self, question: str, session_id: str):
        messages, bundle = super()._build_messages(question, session_id)
        selected_skill = self.select_skill(question)
        if not selected_skill:
            bundle.trace["selected_skill"] = None
            return messages, bundle

        skill_body = selected_skill.get("body") or ""
        bundle.trace["selected_skill"] = {
            "name": selected_skill.get("name", ""),
            "enabled_tools": selected_skill.get("enabled_tools", []),
            "disabled_tools": selected_skill.get("disabled_tools", []),
        }
        if skill_body:
            messages = [SystemMessage(content=skill_body), *messages]
        return messages, bundle

    def build_agent(self):
        return create_deep_agent(
            model=self.model,
            tools=self.default_tools(),
            subagents=[],
            skills=["/skills/"],
            memory=[],
            system_prompt=self.system_prompt,
            # deepagents>=0.7: backend 必须传入“已初始化的实例”，
            # 不再接受 lambda rt: ... 这种 backend factory（会抛
            # "backend must be an initialized backend instance"）。
            store=self.store,
            backend=CompositeBackend(
                default=StateBackend(),
                routes={
                    "/memories/": StoreBackend(
                        namespace=lambda rt: ("deepagent", "memories"),
                        store=self.store,
                    ),
                    "/skills/": FilesystemBackend(
                        root_dir=Path(__file__).resolve().parent.parent,
                        virtual_mode=True,
                    ),
                },
            ),
        )


deep_agent_service = DeepAgentService(streaming=True)
