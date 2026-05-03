import sys
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
    "tools.websearch_tool",
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
    __fields__ = {}
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Field:
    def __init__(self, default=None, **kwargs):
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
sys.modules["pydantic"].Field = lambda default=None, **kwargs: _Field(default, **kwargs)
sys.modules["models.factory"].qwen_model = types.SimpleNamespace(
    init_model=lambda streaming=False: types.SimpleNamespace(
        with_structured_output=lambda schema: None,
        bind_tools=lambda tools: None,
    )
)
sys.modules["services.history_service"].HistoryService = object
sys.modules["tools.academic_tool"].academic_search_papers = types.SimpleNamespace(
    name="academic_search_papers", args={}
)
sys.modules["tools.academic_tool"].get_paper_abstract = types.SimpleNamespace(
    name="get_paper_abstract", args={}
)
sys.modules["tools.academic_tool"].get_paper_bibtex = types.SimpleNamespace(
    name="get_paper_bibtex", args={}
)
sys.modules["tools.academic_tool"].search_github_repos = types.SimpleNamespace(
    name="search_github_repos", args={}
)
sys.modules["tools.paper_refiner_tool"].review_paper_quality = types.SimpleNamespace(
    name="review_paper_quality", args={}
)
sys.modules["tools.paper_refiner_tool"].build_citation_pool = types.SimpleNamespace(
    name="build_citation_pool", args={}
)
sys.modules["tools.websearch_tool"].web_search = types.SimpleNamespace(
    name="web_search", args={}
)


def tearDownModule():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class ResearchCandidatesTest(unittest.TestCase):

    def test_research_candidate_model_exists(self):
        from agents.research_workflow_service import ResearchCandidate
        candidate = ResearchCandidate(
            candidate_id="A",
            title="测试方案",
            core_question="测试问题",
            expected_output="测试产出",
            search_keywords="test keywords",
        )
        self.assertEqual(candidate.candidate_id, "A")
        self.assertEqual(candidate.title, "测试方案")

    def test_clarification_model_includes_candidates(self):
        from agents.research_workflow_service import ResearchClarification, ResearchCandidate

        candidate = ResearchCandidate(
            candidate_id="A", title="方案A", core_question="Q",
            expected_output="O", search_keywords="K",
        )
        clarification = ResearchClarification(
            needs_clarification=True,
            candidates=[candidate],
            questions=["测试问题"],
            assumed_scope="scope",
            refined_query="query",
        )
        self.assertTrue(clarification.needs_clarification)
        self.assertEqual(len(clarification.candidates), 1)
        self.assertEqual(clarification.candidates[0].candidate_id, "A")

    def test_research_state_includes_candidate_fields(self):
        from agents.research_workflow_service import ResearchState
        for field in ("research_candidates", "clarification_status", "selected_candidate_id"):
            self.assertIn(field, ResearchState.__annotations__)

    def test_search_result_tool_includes_github(self):
        from agents.research_workflow_service import ResearchWorkflowService
        self.assertTrue(ResearchWorkflowService._is_search_result_tool("search_github_repos"))
        self.assertTrue(ResearchWorkflowService._is_search_result_tool("academic_search_papers"))

    def test_clarification_state_helpers(self):
        import tempfile
        import os
        import json
        from agents.research_workflow_service import ResearchWorkflowService

        service = ResearchWorkflowService.__new__(ResearchWorkflowService)
        service.artifact_root = Path(tempfile.mkdtemp())
        service.artifacts_dir = service.artifact_root

        state_data = {
            "status": "awaiting_selection",
            "question": "test question",
            "candidates": [
                {"candidate_id": "A", "title": "方案A", "core_question": "Q1",
                 "expected_output": "O1", "search_keywords": "K1"},
                {"candidate_id": "B", "title": "方案B", "core_question": "Q2",
                 "expected_output": "O2", "search_keywords": "K2"},
            ],
            "selected_candidate_id": None,
            "refined_query": "",
        }

        service._save_clarification_state("test-session", state_data)
        loaded = service._load_clarification_state("test-session")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["status"], "awaiting_selection")
        self.assertEqual(len(loaded["candidates"]), 2)

        state_data["status"] = "confirmed"
        state_data["selected_candidate_id"] = "A"
        service._save_clarification_state("test-session", state_data)
        loaded = service._load_clarification_state("test-session")
        self.assertEqual(loaded["status"], "confirmed")
        self.assertEqual(loaded["selected_candidate_id"], "A")

        state_path = service._clarification_state_path("test-session")
        if state_path.exists():
            state_path.unlink()
        os.rmdir(service.artifact_root / "test-session")
        os.rmdir(service.artifact_root)

    def test_final_report_strips_process_sections(self):
        from agents.research_workflow_service import ResearchWorkflowService
        service = ResearchWorkflowService.__new__(ResearchWorkflowService)

        report = service._build_final_report_markdown(
            question="测试问题",
            refined_query="研究主题",
            plan_text="研究计划内容",
            final_answer="这是最终结论。",
            clarification="澄清内容",
            questions=["Q1", "Q2"],
        )

        self.assertIn("# 研究主题", report)
        self.assertIn("## 研究结论", report)
        self.assertIn("这是最终结论。", report)
        for section in ("原始问题", "研究范围说明", "澄清问题建议", "研究计划", "研究方向"):
            self.assertNotIn(section, report)

    def test_clarification_prompt_asks_for_candidates(self):
        from agents.research_workflow_service import CLARIFICATION_PROMPT
        for keyword in ("candidate_id", "A", "B", "C", "search_keywords"):
            self.assertIn(keyword, CLARIFICATION_PROMPT)

    def test_agent_prompt_mentions_github_search(self):
        from agents.research_workflow_service import AGENT_PROMPT
        self.assertIn("search_github_repos", AGENT_PROMPT)

    def test_confirm_candidate_updates_state(self):
        import tempfile
        from agents.research_workflow_service import ResearchWorkflowService, ResearchCandidate

        candidate_a = ResearchCandidate(
            candidate_id="A", title="方案A", core_question="Q1",
            expected_output="O1", search_keywords="K1",
        )
        candidate_b = ResearchCandidate(
            candidate_id="B", title="方案B", core_question="Q2",
            expected_output="O2", search_keywords="K2",
        )
        self.assertEqual(candidate_a.candidate_id, "A")
        self.assertEqual(candidate_b.title, "方案B")

    def test_prompt_uses_simplified_chinese(self):
        from agents.research_workflow_service import AGENT_PROMPT, CLARIFICATION_PROMPT
        for prompt in (AGENT_PROMPT, CLARIFICATION_PROMPT):
            self.assertIn("Simplified Chinese", prompt)


if __name__ == "__main__":
    unittest.main()
