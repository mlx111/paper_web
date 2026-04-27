import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

STUB_MODULES = [
    "langchain_core.messages",
    "langchain_core.tools",
    "langgraph.graph",
    "langgraph.graph.message",
    "loguru",
    "pydantic",
    "models.factory",
    "services.history_service",
    "tools.academic_tool",
    "tools.paper_refiner_tool",
]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in STUB_MODULES}

for name in STUB_MODULES:
    sys.modules.setdefault(name, types.ModuleType(name))


class _Message:
    def __init__(self, content="", **kwargs):
        self.content = content
        for key, value in kwargs.items():
            setattr(self, key, value)


def _tool(name=None, args_schema=None, name_or_callable=None, description=None):
    def decorator(fn):
        fn.name = name or name_or_callable or fn.__name__
        fn.args = {}
        fn.invoke = lambda args: fn(**args)
        return fn

    return decorator


class _BaseModel:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Field:
    def __init__(self, default=None, default_factory=None, **kwargs):
        if default_factory is not None:
            self.default = default_factory()
        else:
            self.default = default


class _StateGraph:
    def __init__(self, *args, **kwargs):
        pass

    def add_node(self, *args, **kwargs):
        pass

    def set_entry_point(self, *args, **kwargs):
        pass

    def add_conditional_edges(self, *args, **kwargs):
        pass

    def add_edge(self, *args, **kwargs):
        pass

    def compile(self):
        return types.SimpleNamespace()


sys.modules["langchain_core.messages"].AIMessage = _Message
sys.modules["langchain_core.messages"].BaseMessage = _Message
sys.modules["langchain_core.messages"].HumanMessage = _Message
sys.modules["langchain_core.messages"].SystemMessage = _Message
sys.modules["langchain_core.messages"].ToolMessage = _Message
sys.modules["langchain_core.tools"].BaseTool = object
sys.modules["langchain_core.tools"].tool = _tool
sys.modules["langgraph.graph"].END = "__end__"
sys.modules["langgraph.graph"].StateGraph = _StateGraph
sys.modules["langgraph.graph.message"].add_messages = lambda left, right: left + right
sys.modules["loguru"].logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)
sys.modules["pydantic"].BaseModel = _BaseModel
sys.modules["pydantic"].Field = lambda default=None, default_factory=None, **kwargs: _Field(
    default, default_factory=default_factory, **kwargs
)
sys.modules["models.factory"].qwen_model = types.SimpleNamespace(
    init_model=lambda streaming=False: types.SimpleNamespace(
        with_structured_output=lambda schema: types.SimpleNamespace(invoke=lambda messages: None),
        bind_tools=lambda tools: types.SimpleNamespace(invoke=lambda messages: None),
        invoke=lambda messages: _Message(content="计划"),
    )
)
sys.modules["services.history_service"].HistoryService = object
sys.modules["tools.academic_tool"].academic_search_papers = types.SimpleNamespace(name="academic_search_papers", args={})
sys.modules["tools.academic_tool"].get_paper_abstract = types.SimpleNamespace(name="get_paper_abstract", args={})
sys.modules["tools.academic_tool"].get_paper_bibtex = types.SimpleNamespace(name="get_paper_bibtex", args={})
sys.modules["tools.paper_refiner_tool"].review_paper_quality = types.SimpleNamespace(name="review_paper_quality", args={})
sys.modules["tools.paper_refiner_tool"].build_citation_pool = types.SimpleNamespace(name="build_citation_pool", args={})


def tearDownModule():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class ResearchWorkflowV2Test(unittest.TestCase):
    def _service(self, root: Path):
        from agents.research_workflow_service import ResearchWorkflowService

        service = ResearchWorkflowService.__new__(ResearchWorkflowService)
        service.artifact_root = root
        return service

    def test_build_artifact_paths_for_research_v2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            paths = service._build_artifact_paths("research_session_abc")

            self.assertEqual(paths["clarification"].name, "clarification.json")
            self.assertEqual(paths["refined_query"].name, "refined_query.json")
            self.assertEqual(paths["final_report"].name, "final_report.md")
            self.assertTrue(paths["clarification"].parent.exists())

    def test_fallback_clarification_for_broad_query(self):
        from agents.research_workflow_service import ResearchWorkflowService

        result = ResearchWorkflowService._fallback_clarification("我想研究 agent 相关的内容")

        self.assertTrue(result.needs_clarification)
        self.assertGreaterEqual(len(result.questions), 1)
        self.assertIn("LLM-based", result.assumed_scope)
        self.assertIn("研究综述", result.refined_query)

    def test_build_final_report_markdown_contains_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            report = service._build_final_report_markdown(
                question="研究 agent",
                refined_query="围绕 LLM-based agents 开展研究综述",
                plan_text="1. 先看综述\n2. 再看应用",
                final_answer="这里是最终研究结论。",
                clarification="默认聚焦于 LLM-based agents。",
                questions=["你更关心综述还是应用？"],
            )

            self.assertIn("## 原始问题", report)
            self.assertIn("## 研究计划", report)
            self.assertIn("## 研究结论", report)
            self.assertIn("这里是最终研究结论。", report)

    def test_persist_research_artifacts_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            artifacts = service._persist_research_artifacts(
                session_id="research_session_abc",
                question="研究 agent",
                clarification_questions=["问题1"],
                clarification_summary="默认聚焦于 LLM-based agents。",
                refined_query="围绕 LLM-based agents 开展研究综述",
                research_plan="1. 看综述",
                final_answer="最终结论",
            )

            clarification_path = Path(artifacts["clarification_path"])
            refined_query_path = Path(artifacts["refined_query_path"])
            report_path = Path(artifacts["report_path"])

            self.assertTrue(clarification_path.exists())
            self.assertTrue(refined_query_path.exists())
            self.assertTrue(report_path.exists())

            clarification_payload = json.loads(clarification_path.read_text(encoding="utf-8"))
            refined_payload = json.loads(refined_query_path.read_text(encoding="utf-8"))
            report_content = report_path.read_text(encoding="utf-8")

            self.assertEqual(clarification_payload["clarification_questions"], ["问题1"])
            self.assertEqual(refined_payload["refined_query"], "围绕 LLM-based agents 开展研究综述")
            self.assertIn("最终结论", report_content)

    def test_clear_session_removes_artifact_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            cleared = []
            service._history = lambda session_id: types.SimpleNamespace(clear=lambda: cleared.append(session_id))
            service._persist_research_artifacts(
                session_id="research_session_abc",
                question="研究 agent",
                clarification_questions=["问题1"],
                clarification_summary="默认聚焦于 LLM-based agents。",
                refined_query="围绕 LLM-based agents 开展研究综述",
                research_plan="1. 看综述",
                final_answer="最终结论",
            )

            self.assertTrue((Path(tmpdir) / "research_session_abc").exists())
            self.assertTrue(service.clear_session("research_session_abc"))
            self.assertEqual(cleared, ["research_session_abc"])
            self.assertFalse((Path(tmpdir) / "research_session_abc").exists())

    def test_extract_final_answer_prefers_agent_message_over_judge_feedback(self):
        from agents.research_workflow_service import ResearchWorkflowService

        service = ResearchWorkflowService.__new__(ResearchWorkflowService)
        messages = [
            sys.modules["langchain_core.messages"].AIMessage(content="研究范围聚焦：默认聚焦于 LLM Agent。", name="clarify"),
            sys.modules["langchain_core.messages"].AIMessage(content="最终研究目标：围绕 LLM Agent 的核心能力展开。", name="refine_query"),
            sys.modules["langchain_core.messages"].AIMessage(content="1. 先看规划能力\n2. 再看工具使用", name="planning"),
            sys.modules["langchain_core.messages"].AIMessage(content="这是正式研究结论。", name="agent"),
            sys.modules["langchain_core.messages"].AIMessage(content="回复内容为空，未提供任何关于AI Agent的研究信息。请补充。", name="judge"),
        ]

        self.assertEqual(service._extract_final_answer(messages), "这是正式研究结论。")

    def test_extract_final_answer_ignores_empty_agent_message(self):
        from agents.research_workflow_service import ResearchWorkflowService

        service = ResearchWorkflowService.__new__(ResearchWorkflowService)
        messages = [
            sys.modules["langchain_core.messages"].AIMessage(content="研究范围聚焦：默认聚焦于 LLM Agent。", name="clarify"),
            sys.modules["langchain_core.messages"].AIMessage(content="", name="agent"),
            sys.modules["langchain_core.messages"].AIMessage(content="请补充更多研究结果。", name="judge"),
        ]

        self.assertEqual(service._extract_final_answer(messages), "")


if __name__ == "__main__":
    unittest.main()
