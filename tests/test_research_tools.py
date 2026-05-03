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
    pass


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


class ResearchToolsTest(unittest.TestCase):
    def test_research_tools_prefer_academic_search_without_deleting_download(self):
        from agents.research_workflow_service import TOOLS, search_papers

        tool_names = [tool.name for tool in TOOLS]

        self.assertIn("academic_search_papers", tool_names)
        self.assertIn("download-paper", tool_names)
        self.assertIn("review_paper_quality", tool_names)
        self.assertIn("build_citation_pool", tool_names)
        self.assertNotIn("search-papers", tool_names)
        self.assertEqual(search_papers.name, "search-papers")

    def test_extract_text_treats_none_as_empty_string(self):
        from agents.research_workflow_service import ResearchWorkflowService

        service = ResearchWorkflowService.__new__(ResearchWorkflowService)
        self.assertEqual(service._extract_text(types.SimpleNamespace(content=None)), "")

    def test_search_result_tool_names_include_academic_search(self):
        from agents.research_workflow_service import ResearchWorkflowService

        self.assertTrue(ResearchWorkflowService._is_search_result_tool("search-papers"))
        self.assertTrue(ResearchWorkflowService._is_search_result_tool("academic_search_papers"))
        self.assertFalse(ResearchWorkflowService._is_search_result_tool("get_paper_bibtex"))

    def test_research_prompts_default_to_simplified_chinese(self):
        from agents.research_workflow_service import AGENT_PROMPT, DECISION_PROMPT, JUDGE_PROMPT, PLANNING_PROMPT

        prompts = [DECISION_PROMPT, PLANNING_PROMPT, AGENT_PROMPT, JUDGE_PROMPT]
        for prompt in prompts:
            self.assertIn("Simplified Chinese", prompt)


if __name__ == "__main__":
    unittest.main()
