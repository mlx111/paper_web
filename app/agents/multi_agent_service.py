"""
多智能体编排服务（supervisor 模式，基于 deepagents 原生 subagents）。

主 agent 作为 Supervisor，通过 deepagents 自动注入的 `task()` 工具把任务分派给
专门子 agent（searcher / analyzer / citation）。子 agent 以 isolated 模式运行，
各自只持有领域工具，独立执行后把精简结论返回给主管；主管综合后给出最终答案。
评测/trace 中，分派动作表现为对 `task` 工具的调用（即 handoff），可被轨迹采集。
"""

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend, StoreBackend

from agents.deep_agent_service import DeepAgentService
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


class MultiAgentService(DeepAgentService):
    """Supervisor + 领域子 agent 的多智能体编排。"""

    context_mode = "deep"

    def get_system_prompt_file(self) -> str:
        return "multi_agent_system.txt"

    # ── 子 agent 规格 ──────────────────────────────────────────────
    def _subagent_specs(self) -> list[dict]:
        return [
            {
                "name": "searcher",
                "description": (
                    "检索专员。负责收集资料：联网搜索 web_search、学术论文检索 "
                    "academic_search_papers、本地知识库检索 retrieve_knowledge。"
                    "当任务需要查找资料、搜索论文或最新信息、检索知识库时，把明确的"
                    "检索需求（含关键词/主题）分派给它；它返回带来源的检索要点。"
                ),
                "system_prompt": (
                    "你是检索专员，只负责信息收集，不写最终答案。根据分派的检索任务，"
                    "选择合适工具（联网搜索/学术检索/知识库检索），可多次调用、交叉验证。"
                    "返回结构化结果：每条资料给出来源、关键要点及其与任务的相关性。"
                    "严禁编造检索结果，查不到就如实说明。"
                ),
                "tools": [web_search, academic_search_papers, retrieve_knowledge],
            },
            {
                "name": "analyzer",
                "description": (
                    "精读分析专员。负责深入理解与评价：读取论文摘要 get_paper_abstract、"
                    "提取文档全文 extract_document_text、评估论文质量 review_paper_quality、"
                    "检索知识库 retrieve_knowledge。当需要精读某篇论文/文档、总结方法、"
                    "评价创新性或可靠性时分派给它（需提供论文标题/URL 或文档路径）。"
                ),
                "system_prompt": (
                    "你是精读分析专员，只负责客观分析给定论文/文档，不做联网泛搜。"
                    "先获取摘要或全文，再从研究问题、方法、实验、创新性、局限性等维度分析。"
                    "所有结论必须基于读到的内容，证据不足处明确说明。"
                ),
                "tools": [
                    get_paper_abstract,
                    extract_document_text,
                    review_paper_quality,
                    retrieve_knowledge,
                ],
            },
            {
                "name": "citation",
                "description": (
                    "引用专员。负责引用与相关工作：生成论文 BibTeX get_paper_bibtex、"
                    "围绕主题构建相关论文引用池 build_citation_pool。当需要规范引用格式、"
                    "或围绕某主题整理相关工作列表时分派给它。"
                ),
                "system_prompt": (
                    "你是引用专员，负责生成规范 BibTeX 引用并整理相关论文列表。"
                    "返回可直接使用的引用条目，并简要说明每篇相关工作与主题的关系。"
                ),
                "tools": [get_paper_bibtex, build_citation_pool],
            },
        ]

    # ── MCP Host 外部工具由父类 DeepAgentService._mcp_tools() 提供 ──

    def build_agent(self):
        # Supervisor 自身只保留轻量工具 + 外部 MCP 工具；
        # 重检索/精读/引用一律通过 task() 分派给领域子 agent。
        supervisor_tools = [get_current_time, *self._mcp_tools()]
        return create_deep_agent(
            model=self.model,
            tools=supervisor_tools,
            subagents=self._subagent_specs(),
            skills=["/skills/"],
            memory=[],
            system_prompt=self.system_prompt,
            store=self.store,
            # deepagents>=0.7: backend 必须传入已初始化实例
            backend=CompositeBackend(
                default=StateBackend(),
                routes={
                    "/memories/": StoreBackend(
                        namespace=lambda rt: ("multiagent", "memories"),
                        store=self.store,
                    ),
                    "/skills/": FilesystemBackend(
                        root_dir=Path(__file__).resolve().parent.parent,
                        virtual_mode=True,
                    ),
                },
            ),
        )


multi_agent_service = MultiAgentService(streaming=True)
