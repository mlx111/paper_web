from __future__ import annotations

import io
import json
import os
import shutil
import ssl
from datetime import datetime, timezone
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Annotated, ClassVar, Literal, Optional, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
try:
    from loguru import logger
except ImportError:  # pragma: no cover - fallback for minimal test environments
    import logging

    logger = logging.getLogger(__name__)
from pydantic import BaseModel, Field

from models.factory import qwen_model
from services.history_service import HistoryService
from tools.academic_tool import academic_search_papers, get_paper_abstract, get_paper_bibtex
from tools.paper_refiner_tool import build_citation_pool, review_paper_quality


try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=None, override=False):  # type: ignore[override]
        """
        Lightweight fallback loader so research can run without python-dotenv.
        """
        if dotenv_path is None:
            return False

        path = Path(dotenv_path)
        if not path.exists():
            return False

        loaded = False
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = value
                loaded = True
        return loaded

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)


class ResearchDecision(BaseModel):
    requires_research: bool = Field(description="Whether the user query requires a full research workflow.")
    answer: Optional[str] = Field(
        default=None,
        description="A direct answer when research is not needed. Use None when full research is required.",
    )


class ResearchJudge(BaseModel):
    is_good_answer: bool = Field(description="Whether the answer is good enough.")
    feedback: Optional[str] = Field(
        default=None,
        description="Short and actionable feedback when the answer is not good enough.",
    )


class ResearchClarification(BaseModel):
    needs_clarification: bool = Field(description="Whether the request is broad enough to need clarification.")
    questions: list[str] = Field(default_factory=list, description="Up to three clarification questions.")
    assumed_scope: str = Field(default="", description="Short Chinese summary of the assumed scope for this round.")
    refined_query: str = Field(
        default="",
        description="A refined Chinese research goal that should guide planning and synthesis.",
    )


class SearchPapersInput(BaseModel):
    query: str = Field(description="The query to search for on the selected archive.")
    max_papers: int = Field(default=3, ge=1, le=10, description="Maximum number of papers to return.")


class ResearchState(TypedDict, total=False):
    requires_research: bool
    num_feedback_requests: int
    is_good_answer: bool
    research_plan: str
    clarification_questions: list[str]
    clarification_summary: str
    refined_query: str
    final_report: str
    research_branches: list[dict[str, Any]]
    aggregated_learnings: list[str]
    branch_sources: list[dict[str, Any]]
    messages: Annotated[Sequence[BaseMessage], add_messages]


class CoreAPIWrapper(BaseModel):
    """Small wrapper around the CORE API."""

    base_url: ClassVar[str] = "https://api.core.ac.uk/v3"
    api_key: ClassVar[str] = os.getenv("CORE_API_KEY", "")
    top_k_results: int = Field(default=3, ge=1, le=10)

    def _request_json(self, query: str) -> dict[str, Any]:
        max_retries = 5
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                params = urllib.parse.urlencode({"q": query, "limit": self.top_k_results})
                request = urllib.request.Request(
                    f"{self.base_url}/search/outputs?{params}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    method="GET",
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = response.read().decode("utf-8", errors="ignore")
                    return json.loads(payload) if payload else {}
            except urllib.error.HTTPError as exc:
                last_error = RuntimeError(f"Got non-2xx response from CORE API: {exc.code} {exc.reason!r}")
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = exc

            if attempt < max_retries - 1:
                import time

                time.sleep(2 ** (attempt + 1))

        raise RuntimeError(f"CORE API search failed: {last_error}")

    def search(self, query: str) -> str:
        response = self._request_json(query)
        results = response.get("results", []) or []
        if not results:
            return "No relevant results were found."

        docs: list[str] = []
        for result in results:
            published_date = result.get("publishedDate") or result.get("yearPublished", "")
            authors = " and ".join([item.get("name", "") for item in result.get("authors", []) if item.get("name")])
            urls = result.get("sourceFulltextUrls") or result.get("downloadUrl", "")
            docs.append(
                "\n".join(
                    [
                        f"* ID: {result.get('id', '')}",
                        f"* Title: {result.get('title', '')}",
                        f"* Published Date: {published_date}",
                        f"* Authors: {authors}",
                        f"* Abstract: {result.get('abstract', '')}",
                        f"* Paper URLs: {urls}",
                    ]
                )
            )
        return "\n-----\n".join(docs)


def _format_tools_description(tools: list[BaseTool]) -> str:
    return "\n\n".join([f"- {tool.name}: {tool.description}\n Input arguments: {tool.args}" for tool in tools])


@tool("search-papers", args_schema=SearchPapersInput)
def search_papers(query: str, max_papers: int = 3) -> str:
    """Search for scientific papers using the CORE API."""
    try:
        return CoreAPIWrapper(top_k_results=max_papers).search(query)
    except Exception as exc:  # pragma: no cover - network dependent
        return f"Error performing paper search: {exc}"


@tool("download-paper")
def download_paper(url: str) -> str:
    """Download a specific scientific paper from a given URL and extract text."""
    try:
        try:
            import pdfplumber
        except ImportError as exc:
            return f"pdfplumber is not installed: {exc}"

        context = ssl._create_unverified_context()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
        }

        max_retries = 5
        for attempt in range(max_retries):
            request = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=60, context=context) as response:
                if 200 <= getattr(response, "status", 200) < 300:
                    pdf_file = io.BytesIO(response.read())
                    text_chunks: list[str] = []
                    with pdfplumber.open(pdf_file) as pdf:
                        for page in pdf.pages:
                            page_text = page.extract_text() or ""
                            if page_text.strip():
                                text_chunks.append(page_text)
                    text = "\n".join(text_chunks).strip()
                    return text if text else "No extractable text was found in the paper."

            if attempt < max_retries - 1:
                import time

                time.sleep(2 ** (attempt + 1))
            else:
                raise RuntimeError("Got non-2xx when downloading paper")
    except urllib.error.HTTPError as exc:
        return f"Error downloading paper: HTTP {exc.code} {exc.reason}"
    except Exception as exc:  # pragma: no cover - network dependent
        return f"Error downloading paper: {exc}"


TOOLS: list[BaseTool] = [
    download_paper,
    academic_search_papers,
    get_paper_abstract,
    get_paper_bibtex,
    review_paper_quality,
    build_citation_pool,
]


DECISION_PROMPT = """
You are an experienced scientific researcher.
Your job is to decide whether the user request needs a real research workflow.

Language policy:
- Respond in Simplified Chinese by default.
- If the user explicitly requests another language, follow the user's request.

Answer directly only for simple conversational questions.
If the request asks for papers, evidence, citations, recent research, comparisons across papers,
or any claim that should be grounded in scientific literature, set requires_research=true.
"""


PLANNING_PROMPT = """
You are an experienced scientific researcher.
Create a clear step-by-step research plan for the user's request.

Language policy:
- Write the plan in Simplified Chinese by default.
- If the user explicitly requests another language, follow the user's request.

Rules:
- Use only the information provided in the conversation and tools.
- Do not guess when evidence is missing.
- If the user gave feedback, incorporate it in the new plan.
- For each step, indicate which tool is needed if any.

Available tools:
{tools}
"""


AGENT_PROMPT = """
You are an experienced scientific researcher.
Follow the research plan and use the available tools to answer the user's request.

Language policy:
- Answer in Simplified Chinese by default.
- If the user explicitly requests another language, follow the user's request.
- Keep paper titles, venue names, and quoted source text in their original language when helpful, but explain them in Chinese.

Requirements:
- Add inline citations when you can.
- Prefer evidence from the papers over unsupported claims.
- Use academic_search_papers for literature search.
- Use download-paper only when a paper URL needs full-text extraction.
- Use get_paper_bibtex when the user needs references.
- Use build_citation_pool when the user asks for related work or recommended citations.
- Use review_paper_quality when the user asks to evaluate a paper, abstract, or paper excerpt.
- If the evidence is insufficient, say so clearly.
"""


JUDGE_PROMPT = """
You are an expert scientific researcher reviewing the final answer.

Language policy:
- Write feedback in Simplified Chinese by default.
- If the user explicitly requests another language, follow the user's request.

Decide whether the answer is satisfactory.
A good answer should:
- Directly answer the user query.
- Be grounded in the retrieved evidence.
- Reflect feedback when present.
- Include inline sources when claims are made.

If the answer is not good enough, provide concise and actionable feedback.
"""


CLARIFICATION_PROMPT = """
You are an experienced scientific researcher.
The user has asked for a research task.

Language policy:
- Respond in Simplified Chinese by default.
- If the user explicitly requests another language, follow the user's request.

Your job:
- Decide whether the topic is broad or ambiguous enough to need clarification.
- Produce up to 3 clarification questions that would help narrow the research.
- Even if no user answers are available yet, produce a practical assumed scope for this round.
- Produce a refined Chinese research goal that is specific enough for planning and report writing.

Return structured output only.
"""


class ResearchWorkflowService:
    """
    Independent scientific-research workflow.

    This service keeps its own history store so it does not mix with chat/file
    conversations. The workflow mirrors the LangGraph tutorial style:
    decision -> planning -> tools -> agent -> judge
    """

    module_name: str = "research"
    report_version: str = "v2.3"

    def __init__(self, streaming: bool = False):
        # 第 1 步：初始化模型与结构化输出包装器。
        # 这里会同时准备三条能力：
        # - decision_llm: 判断要不要进入研究流程
        # - agent_llm: 负责调用论文检索 / 下载工具
        # - judge_llm: 负责给最终答案打分并给反馈
        self.streaming = streaming
        self.model = qwen_model.init_model(streaming)

        self.decision_llm = self.model.with_structured_output(ResearchDecision)
        self.clarify_llm = self.model.with_structured_output(ResearchClarification)
        self.agent_llm = self.model.bind_tools(TOOLS)
        self.judge_llm = self.model.with_structured_output(ResearchJudge)

        # 第 2 步：创建 research 专属历史目录。
        # 这样 research 模块的对话历史不会和 chat / file 混在一起。
        self.project_root = Path(__file__).resolve().parent.parent
        self.history_root = self.project_root / "research_history"
        self.history_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root = self.project_root / "data" / "research"
        self.artifact_root.mkdir(parents=True, exist_ok=True)

        # 第 3 步：构建并编译研究工作流。
        # 这张图只构建一次，后续所有请求复用同一套节点与边。
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile()

        logger.info("Research workflow service initialized, streaming={}", streaming)

    def _history(self, session_id: str) -> HistoryService:
        # research 模块自己的历史存取入口。
        # 这里的 session_id 只对应 research，不会访问其它模块的数据。
        return HistoryService(session_id, self.history_root)

    def _history_messages(self, session_id: str) -> list[BaseMessage]:
        return list(self._history(session_id).messages)

    def _save_turn(self, session_id: str, question: str, answer: str) -> None:
        history = self._history(session_id)
        history.add_messages([HumanMessage(content=question), AIMessage(content=answer)])

    def _build_inputs(self, question: str, session_id: str) -> dict[str, Any]:
        # 把同一个 research 会话里的历史重新载入，
        # 这样模型可以看到本模块内的前文，但不会看到其他模块的历史。
        prior_messages = self._history_messages(session_id)
        return {
            "messages": [*prior_messages, HumanMessage(content=question)],
            "requires_research": False,
            "num_feedback_requests": 0,
            "is_good_answer": False,
            "research_plan": "",
            "clarification_questions": [],
            "clarification_summary": "",
            "refined_query": question,
            "final_report": "",
            "research_branches": [],
            "aggregated_learnings": [],
            "branch_sources": [],
        }

    def _session_storage_dir(self, session_id: str) -> Path:
        session_dir = self.artifact_root / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _build_artifact_paths(self, session_id: str) -> dict[str, Path]:
        session_dir = self._session_storage_dir(session_id)
        return {
            "clarification": session_dir / "clarification.json",
            "refined_query": session_dir / "refined_query.json",
            "branches": session_dir / "branches.json",
            "learnings": session_dir / "learnings.json",
            "sources": session_dir / "sources.json",
            "final_report": session_dir / "final_report.md",
            "report_manifest": session_dir / "report_manifest.json",
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _extract_text(self, message: BaseMessage) -> str:
        content = getattr(message, "content", "")
        if content is None:
            return ""
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
            return "\n".join(parts).strip()
        return str(content).strip()

    @staticmethod
    def _is_search_result_tool(tool_name: str) -> bool:
        return tool_name in {"search-papers", "academic_search_papers"}

    @staticmethod
    def _internal_message_names() -> set[str]:
        return {"clarify", "refine_query", "planning", "judge"}

    def _extract_final_answer(self, messages: Sequence[BaseMessage]) -> str:
        for message in reversed(list(messages)):
            if isinstance(message, AIMessage):
                if getattr(message, "name", "") in self._internal_message_names():
                    continue
                text = self._extract_text(message)
                if text:
                    return text
        return ""

    @staticmethod
    def _latest_user_question(messages: Sequence[BaseMessage]) -> str:
        for message in reversed(list(messages)):
            if isinstance(message, HumanMessage):
                content = getattr(message, "content", "")
                return "" if content is None else str(content).strip()
        return ""

    @staticmethod
    def _fallback_clarification(question: str) -> ResearchClarification:
        broad_markers = ["相关", "内容", "看看", "研究", "介绍", "分析", "agent", "agents", "multi-agent"]
        normalized = (question or "").strip()
        needs = len(normalized) <= 20 or any(marker.lower() in normalized.lower() for marker in broad_markers)
        questions = [
            "你更关注基础概念、代表性论文，还是工程应用？",
            "你希望重点看单智能体、Multi-Agent，还是 LLM-based Agent？",
            "你更关心综述报告、论文清单，还是可落地的系统设计？",
        ] if needs else []
        assumed_scope = "默认聚焦于近年与 LLM-based agents、多智能体协作及工具调用相关的研究进展。"
        refined_query = (
            f"围绕“{normalized}”开展中文研究综述，重点分析核心概念、代表性论文、主流系统架构、应用场景与局限。"
            if normalized
            else "围绕用户主题开展中文研究综述，重点分析概念、代表性论文、架构与局限。"
        )
        result = ResearchClarification()
        result.needs_clarification = needs
        result.questions = questions
        result.assumed_scope = assumed_scope
        result.refined_query = refined_query
        return result

    @staticmethod
    def _normalize_branch(branch: dict[str, Any], index: int) -> dict[str, Any]:
        branch_id = str(branch.get("branch_id") or f"branch_{index + 1}")
        branch_query = str(branch.get("branch_query") or branch.get("query") or "").strip()
        branch_goal = str(branch.get("branch_goal") or branch.get("goal") or branch_query).strip()
        return {
            "branch_id": branch_id,
            "branch_query": branch_query,
            "branch_goal": branch_goal,
            "branch_learnings": list(branch.get("branch_learnings") or []),
            "branch_sources": list(branch.get("branch_sources") or []),
        }

    def _preferred_recent_year_floor(self) -> int:
        return max(2024, datetime.now(timezone.utc).year - 2)

    def _recent_year_suffix(self) -> str:
        current_year = datetime.now(timezone.utc).year
        year_floor = self._preferred_recent_year_floor()
        return " ".join(str(year) for year in range(year_floor, current_year + 1))

    def _recent_research_branches(self, refined_query: str) -> list[dict[str, Any]]:
        query = (refined_query or "研究主题").strip()
        year_suffix = self._recent_year_suffix()
        templates = [
            ("理论基础与关键概念", "梳理核心概念、问题定义和技术脉络"),
            ("最新方法与代表论文", "检索近年代表性论文、方法和实验结论"),
            ("应用场景、局限与未来方向", "总结应用价值、主要限制和后续研究机会"),
        ]
        return [
            self._normalize_branch(
                {
                    "branch_query": f"{query} {topic} {year_suffix}".strip(),
                    "branch_goal": f"{goal}。优先近三年（2024-2026）文献",
                },
                index=index,
            )
            for index, (topic, goal) in enumerate(templates)
        ]

    def _academic_search(self, query: str, max_papers: int = 3, min_year: int | None = None) -> Any:
        year_floor = min_year if min_year is not None else self._preferred_recent_year_floor()
        if hasattr(academic_search_papers, "invoke"):
            return academic_search_papers.invoke({"query": query, "max_papers": max_papers, "min_year": year_floor})
        try:
            return academic_search_papers(query=query, max_papers=max_papers, min_year=year_floor)
        except TypeError:
            return academic_search_papers(query=query, max_papers=max_papers)

    @staticmethod
    def _normalize_sources(raw_sources: Any, branch: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(raw_sources, list):
            source_items = raw_sources
        elif isinstance(raw_sources, dict):
            source_items = raw_sources.get("results") or raw_sources.get("papers") or [raw_sources]
        elif raw_sources:
            source_items = [{"title": "搜索结果", "abstract": str(raw_sources)}]
        else:
            source_items = []

        normalized: list[dict[str, Any]] = []
        for source in source_items:
            if isinstance(source, dict):
                item = dict(source)
            else:
                item = {"title": "搜索结果", "abstract": str(source)}
            item.setdefault("branch_id", branch["branch_id"])
            item.setdefault("branch_query", branch["branch_query"])
            normalized.append(item)
        return normalized

    def _gather_branch_sources(self, branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        gathered: list[dict[str, Any]] = []
        for index, branch in enumerate(branches or []):
            normalized_branch = self._normalize_branch(branch, index)
            raw_sources = self._academic_search(normalized_branch["branch_query"], max_papers=3)
            normalized_branch["branch_sources"] = self._normalize_sources(raw_sources, normalized_branch)
            gathered.append(normalized_branch)
        return gathered

    @staticmethod
    def _source_learning(source: dict[str, Any]) -> str:
        title = str(source.get("title") or source.get("name") or "来源").strip()
        abstract = str(source.get("abstract") or source.get("snippet") or source.get("summary") or "").strip()
        if len(abstract) > 120:
            abstract = abstract[:120].rstrip() + "..."
        return f"{title}: {abstract}" if abstract else title

    def _synthesize_branches(self, branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        synthesized: list[dict[str, Any]] = []
        for index, branch in enumerate(branches or []):
            normalized_branch = self._normalize_branch(branch, index)
            learnings: list[str] = []
            seen: set[str] = set()
            for source in normalized_branch.get("branch_sources", []):
                if not isinstance(source, dict):
                    continue
                learning = self._source_learning(source)
                dedupe_key = str(
                    source.get("abstract") or source.get("snippet") or source.get("summary") or learning
                ).strip().lower()
                if learning and dedupe_key not in seen:
                    seen.add(dedupe_key)
                    learnings.append(learning)
                if len(learnings) >= 5:
                    break
            if not learnings:
                learnings.append(f"{normalized_branch['branch_goal']}：暂无可用来源，需要继续检索。")
            normalized_branch["branch_learnings"] = learnings
            synthesized.append(normalized_branch)
        return synthesized

    @staticmethod
    def _aggregate_learnings(branches: list[dict[str, Any]]) -> list[str]:
        aggregated: list[str] = []
        seen: set[str] = set()
        for branch in branches or []:
            for learning in branch.get("branch_learnings", []) or []:
                text = str(learning).strip()
                dedupe_key = text.lower()
                if text and dedupe_key not in seen:
                    seen.add(dedupe_key)
                    aggregated.append(text)
        return aggregated

    def _persist_branch_artifacts(
        self,
        session_id: str,
        research_branches: list[dict[str, Any]],
        aggregated_learnings: list[str],
        branch_sources: list[dict[str, Any]],
    ) -> dict[str, str]:
        paths = self._build_artifact_paths(session_id)
        normalized_branches = [
            self._normalize_branch(branch, index)
            for index, branch in enumerate(research_branches or [])
        ]
        self._write_json(paths["branches"], {"branches": normalized_branches})
        self._write_json(paths["learnings"], {"learnings": list(aggregated_learnings or [])})
        self._write_json(paths["sources"], {"sources": list(branch_sources or [])})
        return {
            "branches_path": str(paths["branches"]),
            "learnings_path": str(paths["learnings"]),
            "sources_path": str(paths["sources"]),
        }

    def _build_report_manifest(
        self,
        session_id: str,
        question: str,
        research_plan: str,
        final_answer: str,
        research_branches: list[dict[str, Any]],
        aggregated_learnings: list[str],
        branch_sources: list[dict[str, Any]],
        artifacts: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "session_id": session_id,
            "question": question,
            "research_plan": research_plan,
            "final_answer": final_answer,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "branch_count": len(research_branches or []),
            "source_count": len(branch_sources or []),
            "learning_count": len(aggregated_learnings or []),
            "files": {
                "clarification": artifacts.get("clarification_path", ""),
                "refined_query": artifacts.get("refined_query_path", ""),
                "branches": artifacts.get("branches_path", ""),
                "learnings": artifacts.get("learnings_path", ""),
                "sources": artifacts.get("sources_path", ""),
                "final_report": artifacts.get("report_path", ""),
                "manifest": artifacts.get("manifest_path", ""),
            },
        }

    def _load_research_artifacts(self, session_id: str) -> dict[str, Any]:
        paths = self._build_artifact_paths(session_id)
        return {
            "paths": {key: str(value) for key, value in paths.items()},
            "clarification": self._read_json(paths["clarification"], {}),
            "refined_query": self._read_json(paths["refined_query"], {}),
            "branches": self._read_json(paths["branches"], {"branches": []}),
            "learnings": self._read_json(paths["learnings"], {"learnings": []}),
            "sources": self._read_json(paths["sources"], {"sources": []}),
            "final_report": paths["final_report"].read_text(encoding="utf-8") if paths["final_report"].exists() else "",
            "manifest": self._read_json(paths["report_manifest"], {}),
        }

    def reload_research_artifacts(self, session_id: str) -> dict[str, Any]:
        return self._load_research_artifacts(session_id)

    def _summarize_research_artifacts(self, session_id: str) -> dict[str, Any]:
        artifacts = self._load_research_artifacts(session_id)
        manifest = artifacts.get("manifest") or {}
        branches = list((artifacts.get("branches") or {}).get("branches") or [])
        sources = list((artifacts.get("sources") or {}).get("sources") or [])
        report_path = str(artifacts.get("paths", {}).get("final_report") or "")
        manifest_path = str(artifacts.get("paths", {}).get("report_manifest") or "")
        return {
            "research_session_id": session_id,
            "report_version": str(manifest.get("report_version") or self.report_version),
            "report_path": report_path,
            "manifest_path": manifest_path,
            "latest_report_path": report_path,
            "latest_manifest_path": manifest_path,
            "has_branch_data": bool(branches),
            "branch_count": int(manifest.get("branch_count") or len(branches)),
            "source_count": int(manifest.get("source_count") or len(sources)),
            "learning_count": int(manifest.get("learning_count") or len((artifacts.get("learnings") or {}).get("learnings") or [])),
            "can_generate_ppt": bool(report_path),
            "question": str(manifest.get("question") or artifacts.get("clarification", {}).get("question") or ""),
        }

    def _write_report_manifest(
        self,
        session_id: str,
        question: str,
        research_plan: str,
        final_answer: str,
        research_branches: list[dict[str, Any]],
        aggregated_learnings: list[str],
        branch_sources: list[dict[str, Any]],
        artifacts: dict[str, str],
    ) -> dict[str, str]:
        paths = self._build_artifact_paths(session_id)
        manifest = self._build_report_manifest(
            session_id=session_id,
            question=question,
            research_plan=research_plan,
            final_answer=final_answer,
            research_branches=research_branches,
            aggregated_learnings=aggregated_learnings,
            branch_sources=branch_sources,
            artifacts=artifacts,
        )
        self._write_json(paths["report_manifest"], manifest)
        return {"manifest_path": str(paths["report_manifest"])}

    def regenerate_report(self, session_id: str) -> dict[str, str]:
        artifacts = self._load_research_artifacts(session_id)
        clarification = artifacts.get("clarification") or {}
        refined = artifacts.get("refined_query") or {}
        manifest = artifacts.get("manifest") or {}
        research_branches = list((artifacts.get("branches") or {}).get("branches") or [])
        aggregated_learnings = list((artifacts.get("learnings") or {}).get("learnings") or [])
        branch_sources = list((artifacts.get("sources") or {}).get("sources") or [])
        question = str(manifest.get("question") or clarification.get("question") or "")
        research_plan = str(manifest.get("research_plan") or "")
        final_answer = str(manifest.get("final_answer") or "")
        final_report = self._build_final_report_markdown(
            question=question,
            refined_query=str(refined.get("refined_query") or ""),
            plan_text=research_plan,
            final_answer=final_answer,
            clarification=str(clarification.get("clarification_summary") or ""),
            questions=list(clarification.get("clarification_questions") or []),
            research_branches=research_branches,
            aggregated_learnings=aggregated_learnings,
            branch_sources=branch_sources,
        )
        paths = self._build_artifact_paths(session_id)
        self._write_text(paths["final_report"], final_report)
        artifacts_map = {
            "clarification_path": str(paths["clarification"]),
            "refined_query_path": str(paths["refined_query"]),
            "branches_path": str(paths["branches"]),
            "learnings_path": str(paths["learnings"]),
            "sources_path": str(paths["sources"]),
            "report_path": str(paths["final_report"]),
            "manifest_path": str(paths["report_manifest"]),
        }
        self._write_json(
            paths["report_manifest"],
            self._build_report_manifest(
                session_id=session_id,
                question=question,
                research_plan=research_plan,
                final_answer=final_answer,
                research_branches=research_branches,
                aggregated_learnings=aggregated_learnings,
                branch_sources=branch_sources,
                artifacts=artifacts_map,
            ),
        )
        return artifacts_map

    def _build_final_report_markdown(
        self,
        question: str,
        refined_query: str,
        plan_text: str,
        final_answer: str,
        clarification: str,
        questions: list[str],
        research_branches: list[dict[str, Any]] | None = None,
        aggregated_learnings: list[str] | None = None,
        branch_sources: list[dict[str, Any]] | None = None,
    ) -> str:
        title = refined_query or question or "研究主题"
        lines = [
            f"# {title}",
            "",
            "## 原始问题",
            question or "（未提供）",
            "",
            "## 研究范围说明",
            clarification or "本轮未额外生成范围说明。",
            "",
        ]
        if questions:
            lines.extend(["## 澄清问题建议", *[f"- {item}" for item in questions], ""])
        if plan_text:
            plan_lines = [line.rstrip() for line in str(plan_text).splitlines() if line.strip()]
            if plan_lines:
                lines.extend(["## 研究计划", *[f"- {line}" for line in plan_lines], ""])
        if research_branches:
            lines.extend(["## 研究方向"])
            for branch in research_branches:
                lines.append(f"- {branch.get('branch_id', '')}: {branch.get('branch_goal', '')}")
            lines.append("")
        if aggregated_learnings:
            lines.extend(["## 核心发现", *[f"- {item}" for item in aggregated_learnings], ""])
        if branch_sources:
            lines.extend(["## 来源概览"])
            for source in branch_sources:
                title_text = source.get("title") or source.get("name") or "来源"
                branch_id = source.get("branch_id", "")
                lines.append(f"- {branch_id}: {title_text}" if branch_id else f"- {title_text}")
            lines.append("")
        lines.extend(
            [
                "## 研究结论",
                final_answer or "本轮未产出有效研究结论。",
                "",
                "## 说明",
                "本报告由 research workflow 自动生成，用于沉淀本轮研究范围、计划与结论，便于后续继续研究或生成演示材料。",
                "",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def _persist_research_artifacts(
        self,
        session_id: str,
        question: str,
        clarification_questions: list[str],
        clarification_summary: str,
        refined_query: str,
        research_plan: str,
        final_answer: str,
        research_branches: list[dict[str, Any]] | None = None,
        aggregated_learnings: list[str] | None = None,
        branch_sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        paths = self._build_artifact_paths(session_id)
        research_branches = research_branches or []
        aggregated_learnings = aggregated_learnings or []
        branch_sources = branch_sources or []
        self._write_json(
            paths["clarification"],
            {
                "question": question,
                "clarification_questions": clarification_questions,
                "clarification_summary": clarification_summary,
            },
        )
        self._write_json(
            paths["refined_query"],
            {
                "question": question,
                "refined_query": refined_query,
            },
        )
        final_report = self._build_final_report_markdown(
            question=question,
            refined_query=refined_query,
            plan_text=research_plan,
            final_answer=final_answer,
            clarification=clarification_summary,
            questions=clarification_questions,
            research_branches=research_branches,
            aggregated_learnings=aggregated_learnings,
            branch_sources=branch_sources,
        )
        self._write_text(paths["final_report"], final_report)
        branch_artifacts = self._persist_branch_artifacts(
            session_id=session_id,
            research_branches=research_branches,
            aggregated_learnings=aggregated_learnings,
            branch_sources=branch_sources,
        )
        manifest_artifacts = self._write_report_manifest(
            session_id=session_id,
            question=question,
            research_plan=research_plan,
            final_answer=final_answer,
            research_branches=research_branches,
            aggregated_learnings=aggregated_learnings,
            branch_sources=branch_sources,
            artifacts={
                "clarification_path": str(paths["clarification"]),
                "refined_query_path": str(paths["refined_query"]),
                "branches_path": branch_artifacts["branches_path"],
                "learnings_path": branch_artifacts["learnings_path"],
                "sources_path": branch_artifacts["sources_path"],
                "report_path": str(paths["final_report"]),
                "manifest_path": str(paths["report_manifest"]),
            },
        )
        return {
            "clarification_path": str(paths["clarification"]),
            "refined_query_path": str(paths["refined_query"]),
            "report_path": str(paths["final_report"]),
            **manifest_artifacts,
            **branch_artifacts,
        }

    def _build_workflow(self) -> StateGraph:
        # 整体流程图说明：
        # decision_making -> planning -> agent -> tools -> agent -> judge
        # judge 不通过时会回到 planning，形成一个最多两次反馈的修正闭环。
        workflow = StateGraph(ResearchState)

        def decision_making_node(state: ResearchState) -> dict[str, Any]:
            # 节点 1：先判断用户问题是否真的需要论文/文献级研究。
            # 如果只是普通问答，这里会直接返回简答，不进入后续研究流程。
            system_prompt = SystemMessage(content=DECISION_PROMPT)
            response: ResearchDecision = self.decision_llm.invoke([system_prompt] + list(state["messages"]))
            output: dict[str, Any] = {"requires_research": response.requires_research}
            if response.answer:
                output["messages"] = [AIMessage(content=response.answer, name="decision")]
            return output

        def router(state: ResearchState) -> str:
            # 决策节点的分支控制：
            # - 需要研究 -> 进入 planning
            # - 不需要研究 -> 直接结束
            return "clarify" if state["requires_research"] else "end"

        def clarify_node(state: ResearchState) -> dict[str, Any]:
            question = self._latest_user_question(state.get("messages", []))
            system_prompt = SystemMessage(content=CLARIFICATION_PROMPT)
            try:
                response: ResearchClarification = self.clarify_llm.invoke([system_prompt] + list(state["messages"]))
            except Exception:
                response = self._fallback_clarification(question)

            summary = response.assumed_scope or "本轮按默认研究范围继续推进。"
            refined_query = response.refined_query or self._fallback_clarification(question).refined_query
            return {
                "clarification_questions": list(response.questions or []),
                "clarification_summary": summary,
                "refined_query": refined_query,
                "messages": [AIMessage(content=f"研究范围聚焦：{summary}\n\n增强研究目标：{refined_query}", name="clarify")],
            }

        def refine_query_node(state: ResearchState) -> dict[str, Any]:
            refined_query = state.get("refined_query", "").strip()
            clarification_summary = state.get("clarification_summary", "").strip()
            question = self._latest_user_question(state.get("messages", []))
            if not refined_query:
                refined_query = self._fallback_clarification(question).refined_query
            content = f"最终研究目标：{refined_query}"
            if clarification_summary:
                content += f"\n\n范围说明：{clarification_summary}"
            return {
                "refined_query": refined_query,
                "messages": [AIMessage(content=content, name="refine_query")],
            }

        def expand_node(state: ResearchState) -> dict[str, Any]:
            refined_query = state.get("refined_query", "").strip()
            branches = self._recent_research_branches(refined_query)
            summary = "\n".join(
                f"- {branch['branch_id']}: {branch['branch_goal']} ({branch['branch_query']})"
                for branch in branches
            )
            return {
                "research_branches": branches,
                "messages": [AIMessage(content=f"研究分支：\n{summary}", name="expand")],
            }

        def branch_gather_node(state: ResearchState) -> dict[str, Any]:
            branches = self._gather_branch_sources(list(state.get("research_branches") or []))
            branch_sources = [
                source
                for branch in branches
                for source in branch.get("branch_sources", [])
            ]
            summary = "\n".join(
                f"- {branch['branch_id']}: 收集到 {len(branch.get('branch_sources', []))} 条来源"
                for branch in branches
            )
            return {
                "research_branches": branches,
                "branch_sources": branch_sources,
                "messages": [AIMessage(content=f"分支检索完成：\n{summary}", name="branch_gather")],
            }

        def branch_synthesize_node(state: ResearchState) -> dict[str, Any]:
            branches = self._synthesize_branches(list(state.get("research_branches") or []))
            learnings = self._aggregate_learnings(branches)
            summary = "\n".join(f"- {item}" for item in learnings)
            return {
                "research_branches": branches,
                "aggregated_learnings": learnings,
                "messages": [AIMessage(content=f"分支发现汇总：\n{summary}", name="branch_synthesize")],
            }

        def planning_node(state: ResearchState) -> dict[str, Any]:
            # 节点 2：生成研究计划。
            # 这里会让模型先把任务拆成步骤，并提示每一步大概该用什么工具。
            system_prompt = SystemMessage(
                content=(
                    PLANNING_PROMPT.format(tools=_format_tools_description(TOOLS))
                    + f"\n\nRefined research goal:\n{state.get('refined_query', '')}"
                    + (
                        "\n\nAggregated learnings from branch research:\n"
                        + "\n".join(f"- {item}" for item in state.get("aggregated_learnings", []))
                        if state.get("aggregated_learnings")
                        else ""
                    )
                    + (
                        f"\n\nAssumed scope:\n{state.get('clarification_summary', '')}"
                        if state.get("clarification_summary")
                        else ""
                    )
                )
            )
            response = self.model.invoke([system_prompt] + list(state["messages"]))
            plan_text = self._extract_text(response)
            return {
                "research_plan": plan_text,
                "messages": [AIMessage(content=plan_text, name="planning")],
            }

        def tools_node(state: ResearchState) -> dict[str, Any]:
            # 节点 3：执行模型在上一轮中请求的工具。
            # 例如 search-papers / download-paper，结果会被包装成 ToolMessage 再回流给 agent。
            outputs: list[ToolMessage] = []
            last_message = state["messages"][-1]
            for tool_call in getattr(last_message, "tool_calls", []) or []:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", "")
                tool_result = next((tool for tool in TOOLS if tool.name == tool_name), None)
                if tool_result is None:
                    outputs.append(
                        ToolMessage(
                            content=json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False),
                            name=tool_name,
                            tool_call_id=tool_id,
                        )
                    )
                    continue

                result = tool_result.invoke(tool_args)
                outputs.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
                        name=tool_name,
                        tool_call_id=tool_id,
                    )
                )
            return {"messages": outputs}

        def agent_node(state: ResearchState) -> dict[str, Any]:
            # 节点 4：综合计划 + 工具结果，生成面向用户的研究回答。
            # 如果模型觉得证据还不够，它还可以继续发起工具调用。
            plan_text = state.get("research_plan", "")
            refined_query = state.get("refined_query", "")
            clarification_summary = state.get("clarification_summary", "")
            aggregated_learnings = state.get("aggregated_learnings", [])
            learning_context = (
                "\n\nAggregated learnings:\n" + "\n".join(f"- {item}" for item in aggregated_learnings)
                if aggregated_learnings
                else ""
            )
            system_prompt = SystemMessage(
                content=(
                    f"{AGENT_PROMPT}\n\nRefined research goal:\n{refined_query}\n\nResearch plan:\n{plan_text}"
                    + learning_context
                    + (f"\n\nAssumed scope:\n{clarification_summary}" if clarification_summary else "")
                )
                if plan_text or refined_query
                else AGENT_PROMPT
            )
            response = self.agent_llm.invoke([system_prompt] + list(state["messages"]))
            if isinstance(response, AIMessage):
                response.name = "agent"
            return {"messages": [response]}

        def should_continue(state: ResearchState) -> str:
            # agent 节点如果还带着 tool_calls，就说明它还想继续查证，
            # 因此回到 tools；否则进入 judge 进行质量检查。
            last_message = state["messages"][-1]
            tool_calls = getattr(last_message, "tool_calls", None)
            return "continue" if tool_calls else "end"

        def judge_node(state: ResearchState) -> dict[str, Any]:
            # 节点 5：质量检查。
            # 如果答案还不够好，就给出 feedback，然后回到 planning 再迭代一轮。
            num_feedback_requests = state.get("num_feedback_requests", 0)
            if num_feedback_requests >= 2:
                return {"is_good_answer": True}

            system_prompt = SystemMessage(content=JUDGE_PROMPT)
            response: ResearchJudge = self.judge_llm.invoke([system_prompt] + list(state["messages"]))
            output: dict[str, Any] = {
                "is_good_answer": response.is_good_answer,
                "num_feedback_requests": num_feedback_requests + 1,
            }
            if response.feedback:
                output["messages"] = [AIMessage(content=response.feedback, name="judge")]
            return output

        def final_answer_router(state: ResearchState) -> str:
            # judge 通过 -> 结束
            # judge 不通过 -> 回到 planning 再做一轮研究
            return "end" if state["is_good_answer"] else "planning"

        workflow.add_node("decision_making", decision_making_node)
        workflow.add_node("clarify", clarify_node)
        workflow.add_node("refine_query", refine_query_node)
        workflow.add_node("expand", expand_node)
        workflow.add_node("branch_gather", branch_gather_node)
        workflow.add_node("branch_synthesize", branch_synthesize_node)
        workflow.add_node("planning", planning_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("agent", agent_node)
        workflow.add_node("judge", judge_node)

        workflow.set_entry_point("decision_making")
        workflow.add_conditional_edges(
            "decision_making",
            router,
            {"clarify": "clarify", "end": END},
        )
        workflow.add_edge("clarify", "refine_query")
        workflow.add_edge("refine_query", "expand")
        workflow.add_edge("expand", "branch_gather")
        workflow.add_edge("branch_gather", "branch_synthesize")
        workflow.add_edge("branch_synthesize", "planning")
        workflow.add_edge("planning", "agent")
        workflow.add_edge("tools", "agent")
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {"continue": "tools", "end": "judge"},
        )
        workflow.add_conditional_edges(
            "judge",
            final_answer_router,
            {"planning": "planning", "end": END},
        )

        return workflow

    async def query(self, question: str, session_id: str) -> str:
        try:
            # 非流式入口：
            # 一次性跑完整张图，最后直接返回最终答案。
            logger.info("[research {}] start query: {}", session_id, question)
            inputs = self._build_inputs(question, session_id)
            result = await self.app.ainvoke(inputs)
            messages = result.get("messages", []) if isinstance(result, dict) else []
            answer = self._extract_final_answer(messages)
            if isinstance(result, dict):
                self._persist_research_artifacts(
                    session_id=session_id,
                    question=question,
                    clarification_questions=list(result.get("clarification_questions") or []),
                    clarification_summary=str(result.get("clarification_summary") or ""),
                    refined_query=str(result.get("refined_query") or question),
                    research_plan=str(result.get("research_plan") or ""),
                    final_answer=answer,
                    research_branches=list(result.get("research_branches") or []),
                    aggregated_learnings=list(result.get("aggregated_learnings") or []),
                    branch_sources=list(result.get("branch_sources") or []),
                )
            if answer:
                self._save_turn(session_id, question, answer)
            return answer
        except Exception as exc:
            logger.error("[research {}] query failed: {}", session_id, exc)
            logger.error("Exception traceback:\n{}", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            raise

    async def query_stream(self, question: str, session_id: str):
        try:
            # 流式入口：
            # 按节点把中间过程不断吐给前端，方便展示研究进度和工具调用过程。
            logger.info("[research {}] start stream query: {}", session_id, question)
            inputs = self._build_inputs(question, session_id)
            streamed_messages: list[BaseMessage] = []
            final_state_values: dict[str, Any] = {}

            async for chunk in self.app.astream(inputs, stream_mode="updates"):
                for node_name, updates in chunk.items():
                    if not isinstance(updates, dict):
                        continue
                    final_state_values.update({key: value for key, value in updates.items() if key != "messages"})

                    messages = updates.get("messages") or []
                    if not isinstance(messages, list):
                        continue

                    for message in messages:
                        streamed_messages.append(message)
                        message_type = type(message).__name__

                        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
                            # 这里把模型发起的工具调用单独作为事件发出去，
                            # 前端可以据此显示“正在检索论文 / 正在下载全文”之类的状态。
                            for tool_call in message.tool_calls:
                                yield {
                                    "type": "tool_call",
                                    "node": node_name,
                                    "data": {
                                        "tool_name": tool_call.get("name", "unknown"),
                                        "arguments": tool_call.get("args", {}),
                                    },
                                }
                            continue

                        if isinstance(message, ToolMessage):
                            # 工具返回的原始结果也单独透出。
                            # search-papers 会被标成 search_results，方便前端区分。
                            event_type = "search_results" if self._is_search_result_tool(message.name or "") else "content"
                            yield {
                                "type": event_type,
                                "node": node_name,
                                "data": message.content,
                            }
                            continue

                        if isinstance(message, AIMessage):
                            # planning / judge / 其它 AI 中间消息也可以透出，
                            # 这样后面排查流程时能看清楚每一步发生了什么。
                            text = self._extract_text(message)
                            if text:
                                message_name = getattr(message, "name", "")
                                if (
                                    node_name in {"planning", "judge", "expand", "branch_gather", "branch_synthesize"}
                                    or message_name in {"clarify", "refine_query", "judge", "expand", "branch_gather", "branch_synthesize"}
                                ):
                                    yield {"type": "debug", "node": node_name, "message_type": message_type, "data": text}
                                else:
                                    yield {"type": "content", "node": node_name, "data": text}
                            continue

                        if isinstance(message, HumanMessage):
                            continue

                        # Anything else is emitted as debug info for inspection.
                        yield {"type": "debug", "node": node_name, "message_type": message_type, "data": self._extract_text(message)}

            # 流程结束后，把最终答案写回 research 专属历史，
            # 方便下一次同模块会话继续沿用这段上下文。
            final_answer = self._extract_final_answer(streamed_messages)
            if final_answer:
                self._save_turn(session_id, question, final_answer)

            artifacts = self._persist_research_artifacts(
                session_id=session_id,
                question=question,
                clarification_questions=list(final_state_values.get("clarification_questions") or []),
                clarification_summary=str(final_state_values.get("clarification_summary") or ""),
                refined_query=str(final_state_values.get("refined_query") or question),
                research_plan=str(final_state_values.get("research_plan") or ""),
                final_answer=final_answer,
                research_branches=list(final_state_values.get("research_branches") or []),
                aggregated_learnings=list(final_state_values.get("aggregated_learnings") or []),
                branch_sources=list(final_state_values.get("branch_sources") or []),
            )

            yield {
                "type": "complete",
                "data": {
                    "answer": final_answer,
                    "module": self.module_name,
                    "artifacts": artifacts,
                    "report_path": artifacts.get("report_path", ""),
                    "refined_query": str(final_state_values.get("refined_query") or question),
                },
            }
        except Exception as exc:
            logger.error("[research {}] stream failed: {}", session_id, exc)
            logger.error("Exception traceback:\n{}", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            yield {"type": "error", "data": str(exc)}

    def get_session_history(self, session_id: str) -> list[dict[str, Any]]:
        try:
            messages = self._history_messages(session_id)
            artifacts_summary = self._summarize_research_artifacts(session_id)
            history: list[dict[str, Any]] = []
            for index, msg in enumerate(messages):
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                entry = {
                    "role": role,
                    "content": self._extract_text(msg),
                    "timestamp": getattr(msg, "timestamp", None),
                }
                if index == len(messages) - 1 and role == "assistant":
                    entry["artifacts"] = artifacts_summary
                history.append(entry)
            return history
        except Exception as exc:
            logger.error("[research {}] get_session_history failed: {}", session_id, exc)
            return []

    def clear_session(self, session_id: str) -> bool:
        try:
            self._history(session_id).clear()
            session_dir = self.artifact_root / str(session_id)
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
            return True
        except Exception as exc:
            logger.error("[research {}] clear_session failed: {}", session_id, exc)
            return False


research_workflow_service = ResearchWorkflowService(streaming=True)
