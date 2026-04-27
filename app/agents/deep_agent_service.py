from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend, StoreBackend

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
    def build_agent(self):
        return create_deep_agent(
            model=self.model,
            tools=[
                retrieve_knowledge,
                get_current_time,
                web_search,
                academic_search_papers,
                get_paper_abstract,
                get_paper_bibtex,
                review_paper_quality,
                build_citation_pool,
                extract_document_text,
            ],
            subagents=[],
            skills=["/skills/"],
            memory=[],
            system_prompt=self.system_prompt,
            # deepagent 这里继续保留 store / backend
            store=self.store,
            backend=lambda rt: CompositeBackend(
                default=StateBackend(rt),
                routes={
                    "/memories/": StoreBackend(rt),
                    "/skills/": FilesystemBackend(
                        root_dir=Path(__file__).resolve().parent.parent,
                        virtual_mode=True,
                    ),
                },
            ),
        )


deep_agent_service = DeepAgentService(streaming=True)
