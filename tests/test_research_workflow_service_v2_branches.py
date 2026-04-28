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


class ResearchWorkflowV22Test(unittest.TestCase):
    def _service(self, root: Path):
        from agents.research_workflow_service import ResearchWorkflowService

        service = ResearchWorkflowService.__new__(ResearchWorkflowService)
        service.artifact_root = root
        return service

    def test_branch_artifact_paths_and_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            paths = service._build_artifact_paths("research_session_abc")
            branch = service._normalize_branch(
                {
                    "branch_query": "LLM Agent 规划能力",
                    "branch_goal": "梳理规划能力相关论文",
                },
                index=0,
            )

            self.assertEqual(paths["branches"].name, "branches.json")
            self.assertEqual(paths["learnings"].name, "learnings.json")
            self.assertEqual(paths["sources"].name, "sources.json")
            self.assertEqual(branch["branch_id"], "branch_1")
            self.assertEqual(branch["branch_query"], "LLM Agent 规划能力")
            self.assertEqual(branch["branch_goal"], "梳理规划能力相关论文")
            self.assertEqual(branch["branch_learnings"], [])
            self.assertEqual(branch["branch_sources"], [])

    def test_expand_creates_three_distinct_chinese_branches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            branches = service._initial_research_branches("围绕 LLM Agent 进行研究综述")

            self.assertEqual(len(branches), 3)
            self.assertEqual(len({item["branch_query"] for item in branches}), 3)
            self.assertTrue(all("LLM Agent" in item["branch_query"] for item in branches))
            self.assertTrue(all(item["branch_goal"] for item in branches))
            self.assertTrue(all(item["branch_id"].startswith("branch_") for item in branches))

    def test_gather_adds_sources_to_each_branch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            seen_queries = []

            def fake_search(query, max_papers=3):
                seen_queries.append(query)
                return [{"title": f"Paper for {query}", "abstract": "Finding", "url": "https://example.test/paper"}]

            service._academic_search = fake_search
            branches = [
                service._normalize_branch({"branch_query": "方向 A", "branch_goal": "目标 A"}, 0),
                service._normalize_branch({"branch_query": "方向 B", "branch_goal": "目标 B"}, 1),
            ]

            gathered = service._gather_branch_sources(branches)

            self.assertEqual(seen_queries, ["方向 A", "方向 B"])
            self.assertEqual(len(gathered), 2)
            self.assertEqual(gathered[0]["branch_sources"][0]["title"], "Paper for 方向 A")
            self.assertEqual(gathered[1]["branch_sources"][0]["title"], "Paper for 方向 B")

    def test_synthesize_adds_branch_and_aggregated_learnings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            branches = [
                service._normalize_branch(
                    {
                        "branch_query": "方向 A",
                        "branch_goal": "目标 A",
                        "branch_sources": [
                            {"title": "Paper A", "abstract": "Agent planning improves tool use."},
                            {"title": "Paper A duplicate", "abstract": "Agent planning improves tool use."},
                        ],
                    },
                    0,
                ),
                service._normalize_branch(
                    {
                        "branch_query": "方向 B",
                        "branch_goal": "目标 B",
                        "branch_sources": [{"title": "Paper B", "abstract": "Multi-agent coordination needs evaluation."}],
                    },
                    1,
                ),
            ]

            synthesized = service._synthesize_branches(branches)
            aggregated = service._aggregate_learnings(synthesized)

            self.assertGreaterEqual(len(synthesized[0]["branch_learnings"]), 1)
            self.assertLessEqual(len(synthesized[0]["branch_learnings"]), 5)
            self.assertIn("Paper A", synthesized[0]["branch_learnings"][0])
            self.assertEqual(len(aggregated), 2)

    def test_report_and_artifacts_include_branch_learnings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            branches = [
                service._normalize_branch(
                    {
                        "branch_query": "方向 A",
                        "branch_goal": "目标 A",
                        "branch_learnings": ["Paper A: Agent planning improves tool use."],
                        "branch_sources": [{"title": "Paper A", "abstract": "Agent planning improves tool use."}],
                    },
                    0,
                )
            ]
            artifacts = service._persist_research_artifacts(
                session_id="research_session_abc",
                question="研究 agent",
                clarification_questions=[],
                clarification_summary="默认聚焦 LLM Agent。",
                refined_query="围绕 LLM Agent 进行研究综述",
                research_plan="1. 多分支研究",
                final_answer="最终结论",
                research_branches=branches,
                aggregated_learnings=["Paper A: Agent planning improves tool use."],
                branch_sources=branches[0]["branch_sources"],
            )

            report = Path(artifacts["report_path"]).read_text(encoding="utf-8")
            branches_payload = json.loads(Path(artifacts["branches_path"]).read_text(encoding="utf-8"))
            learnings_payload = json.loads(Path(artifacts["learnings_path"]).read_text(encoding="utf-8"))
            sources_payload = json.loads(Path(artifacts["sources_path"]).read_text(encoding="utf-8"))

            self.assertIn("## 研究方向", report)
            self.assertIn("## 核心发现", report)
            self.assertIn("## 来源概览", report)
            self.assertEqual(branches_payload["branches"][0]["branch_id"], "branch_1")
            self.assertEqual(learnings_payload["learnings"], ["Paper A: Agent planning improves tool use."])
            self.assertEqual(sources_payload["sources"][0]["title"], "Paper A")


if __name__ == "__main__":
    unittest.main()
