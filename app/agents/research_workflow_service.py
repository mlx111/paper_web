from __future__ import annotations

import io
import json
import os
import ssl
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
from loguru import logger
from pydantic import BaseModel, Field

from models.factory import qwen_model
from services.history_service import HistoryService


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


class SearchPapersInput(BaseModel):
    query: str = Field(description="The query to search for on the selected archive.")
    max_papers: int = Field(default=3, ge=1, le=10, description="Maximum number of papers to return.")


class ResearchState(TypedDict, total=False):
    requires_research: bool
    num_feedback_requests: int
    is_good_answer: bool
    research_plan: str
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


TOOLS: list[BaseTool] = [search_papers, download_paper]


DECISION_PROMPT = """
You are an experienced scientific researcher.
Your job is to decide whether the user request needs a real research workflow.

Answer directly only for simple conversational questions.
If the request asks for papers, evidence, citations, recent research, comparisons across papers,
or any claim that should be grounded in scientific literature, set requires_research=true.
"""


PLANNING_PROMPT = """
You are an experienced scientific researcher.
Create a clear step-by-step research plan for the user's request.

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

Requirements:
- Add inline citations when you can.
- Prefer evidence from the papers over unsupported claims.
- If the evidence is insufficient, say so clearly.
"""


JUDGE_PROMPT = """
You are an expert scientific researcher reviewing the final answer.

Decide whether the answer is satisfactory.
A good answer should:
- Directly answer the user query.
- Be grounded in the retrieved evidence.
- Reflect feedback when present.
- Include inline sources when claims are made.

If the answer is not good enough, provide concise and actionable feedback.
"""


class ResearchWorkflowService:
    """
    Independent scientific-research workflow.

    This service keeps its own history store so it does not mix with chat/file
    conversations. The workflow mirrors the LangGraph tutorial style:
    decision -> planning -> tools -> agent -> judge
    """

    module_name: str = "research"

    def __init__(self, streaming: bool = False):
        # 第 1 步：初始化模型与结构化输出包装器。
        # 这里会同时准备三条能力：
        # - decision_llm: 判断要不要进入研究流程
        # - agent_llm: 负责调用论文检索 / 下载工具
        # - judge_llm: 负责给最终答案打分并给反馈
        self.streaming = streaming
        self.model = qwen_model.init_model(streaming)

        self.decision_llm = self.model.with_structured_output(ResearchDecision)
        self.agent_llm = self.model.bind_tools(TOOLS)
        self.judge_llm = self.model.with_structured_output(ResearchJudge)

        # 第 2 步：创建 research 专属历史目录。
        # 这样 research 模块的对话历史不会和 chat / file 混在一起。
        self.project_root = Path(__file__).resolve().parent.parent
        self.history_root = self.project_root / "research_history"
        self.history_root.mkdir(parents=True, exist_ok=True)

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
        }

    def _extract_text(self, message: BaseMessage) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
            return "\n".join(parts).strip()
        return str(content).strip()

    def _extract_final_answer(self, messages: Sequence[BaseMessage]) -> str:
        for message in reversed(list(messages)):
            if isinstance(message, AIMessage):
                text = self._extract_text(message)
                if text:
                    return text
        return ""

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
                output["messages"] = [AIMessage(content=response.answer)]
            return output

        def router(state: ResearchState) -> str:
            # 决策节点的分支控制：
            # - 需要研究 -> 进入 planning
            # - 不需要研究 -> 直接结束
            return "planning" if state["requires_research"] else "end"

        def planning_node(state: ResearchState) -> dict[str, Any]:
            # 节点 2：生成研究计划。
            # 这里会让模型先把任务拆成步骤，并提示每一步大概该用什么工具。
            system_prompt = SystemMessage(
                content=PLANNING_PROMPT.format(tools=_format_tools_description(TOOLS))
            )
            response = self.model.invoke([system_prompt] + list(state["messages"]))
            plan_text = self._extract_text(response)
            return {
                "research_plan": plan_text,
                "messages": [AIMessage(content=plan_text)],
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
            system_prompt = SystemMessage(
                content=f"{AGENT_PROMPT}\n\nResearch plan:\n{plan_text}" if plan_text else AGENT_PROMPT
            )
            response = self.agent_llm.invoke([system_prompt] + list(state["messages"]))
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
                output["messages"] = [AIMessage(content=response.feedback)]
            return output

        def final_answer_router(state: ResearchState) -> str:
            # judge 通过 -> 结束
            # judge 不通过 -> 回到 planning 再做一轮研究
            return "end" if state["is_good_answer"] else "planning"

        workflow.add_node("decision_making", decision_making_node)
        workflow.add_node("planning", planning_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("agent", agent_node)
        workflow.add_node("judge", judge_node)

        workflow.set_entry_point("decision_making")
        workflow.add_conditional_edges(
            "decision_making",
            router,
            {"planning": "planning", "end": END},
        )
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

            async for chunk in self.app.astream(inputs, stream_mode="updates"):
                for node_name, updates in chunk.items():
                    if not isinstance(updates, dict):
                        continue

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
                            event_type = "search_results" if message.name == "search-papers" else "content"
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
                                if node_name == "planning":
                                    yield {"type": "debug", "node": node_name, "message_type": message_type, "data": text}
                                elif node_name == "judge":
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

            yield {"type": "complete", "data": {"answer": final_answer, "module": self.module_name}}
        except Exception as exc:
            logger.error("[research {}] stream failed: {}", session_id, exc)
            logger.error("Exception traceback:\n{}", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            yield {"type": "error", "data": str(exc)}

    def get_session_history(self, session_id: str) -> list[dict[str, Any]]:
        try:
            messages = self._history_messages(session_id)
            history: list[dict[str, Any]] = []
            for msg in messages:
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                history.append(
                    {
                        "role": role,
                        "content": self._extract_text(msg),
                        "timestamp": getattr(msg, "timestamp", None),
                    }
                )
            return history
        except Exception as exc:
            logger.error("[research {}] get_session_history failed: {}", session_id, exc)
            return []

    def clear_session(self, session_id: str) -> bool:
        try:
            self._history(session_id).clear()
            return True
        except Exception as exc:
            logger.error("[research {}] clear_session failed: {}", session_id, exc)
            return False


research_workflow_service = ResearchWorkflowService(streaming=True)
