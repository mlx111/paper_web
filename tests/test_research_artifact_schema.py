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


class ResearchArtifactSchemaTest(unittest.TestCase):
    def _service(self, root: Path):
        from agents.research_workflow_service import ResearchWorkflowService

        service = ResearchWorkflowService.__new__(ResearchWorkflowService)
        service.artifact_root = root
        return service

    def test_manifest_path_and_payload_are_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(Path(tmpdir))
            paths = service._build_artifact_paths("research_session_abc")
            artifacts = service._persist_research_artifacts(
                session_id="research_session_abc",
                question="研究 agent",
                clarification_questions=["问题1"],
                clarification_summary="默认聚焦于 LLM-based agents。",
                refined_query="围绕 LLM-based agents 开展研究综述",
                research_plan="1. 看综述",
                final_answer="最终结论",
                research_branches=[
                    service._normalize_branch(
                        {
                            "branch_query": "方向 A",
                            "branch_goal": "目标 A",
                            "branch_learnings": ["A: learn"],
                            "branch_sources": [{"title": "Paper A", "abstract": "learn"}],
                        },
                        0,
                    )
                ],
                aggregated_learnings=["A: learn"],
                branch_sources=[{"title": "Paper A", "abstract": "learn", "branch_id": "branch_1"}],
            )

            self.assertEqual(paths["report_manifest"].name, "report_manifest.json")
            manifest = json.loads(Path(artifacts["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["report_version"], "v2.3")
            self.assertEqual(manifest["branch_count"], 1)
            self.assertEqual(manifest["source_count"], 1)
            self.assertEqual(manifest["files"]["final_report"], artifacts["report_path"])


if __name__ == "__main__":
    unittest.main()
