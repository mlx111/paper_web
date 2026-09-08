import sys
import types
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

for name in [
    "deepagents",
    "deepagents.backends",
    "agents.Base_agent_service",
    "langchain_core.messages",
]:
    sys.modules.setdefault(name, types.ModuleType(name))

tools_module = sys.modules.setdefault("tools", types.ModuleType("tools"))
tools_module.__path__ = [str(APP_DIR / "tools")]
utils_module = sys.modules.setdefault("utils", types.ModuleType("utils"))
utils_module.__path__ = [str(APP_DIR / "utils")]


def _tool(name):
    def fn():
        return name
    fn.name = name
    fn.__name__ = name
    return fn


sys.modules["deepagents"].create_deep_agent = lambda **kwargs: kwargs
sys.modules["deepagents.backends"].CompositeBackend = object
sys.modules["deepagents.backends"].FilesystemBackend = object
sys.modules["deepagents.backends"].StateBackend = object
sys.modules["deepagents.backends"].StoreBackend = object


class _SystemMessage:
    def __init__(self, content):
        self.content = content


sys.modules["langchain_core.messages"].SystemMessage = _SystemMessage


class _BaseAgentService:
    def __init__(self, *args, **kwargs):
        pass

    def _build_messages(self, question, session_id):
        bundle = types.SimpleNamespace(
            mode="deep",
            routing_hints={},
            final_context="base context",
            trace={},
        )
        return [_SystemMessage("base context")], bundle


sys.modules["agents.Base_agent_service"].BaseAgentService = _BaseAgentService
for tool_name in [
    "academic_search_papers",
    "build_citation_pool",
    "extract_document_text",
    "get_current_time",
    "get_paper_abstract",
    "get_paper_bibtex",
    "retrieve_knowledge",
    "review_paper_quality",
    "web_search",
]:
    setattr(sys.modules["tools"], tool_name, _tool(tool_name))
from agents.deep_agent_service import DeepAgentService


class FakeSkill:
    name = "paper-analyzer"
    enabled_tools = ["retrieve_knowledge", "web_search"]
    disabled_tools = ["web_search"]

    def resolve_body(self, variables=None):
        return "Analyze paper"


class FakeRegistry:
    def find_by_trigger(self, text):
        return [FakeSkill()] if "paper" in text else []


def test_deep_agent_selects_skill_and_filters_tools():
    service = DeepAgentService.__new__(DeepAgentService)
    service.skill_registry = FakeRegistry()

    selected = service.select_skill("please analyze this paper")
    tools = service.filter_tools_for_skill(service.default_tools(), selected)

    assert selected["name"] == "paper-analyzer"
    assert selected["body"] == "Analyze paper"
    assert [tool.name for tool in tools] == ["retrieve_knowledge"]


def test_deep_agent_keeps_all_tools_when_no_skill_matches():
    service = DeepAgentService.__new__(DeepAgentService)
    service.skill_registry = FakeRegistry()

    selected = service.select_skill("hello")
    tools = service.filter_tools_for_skill(service.default_tools(), selected)

    assert selected is None
    assert len(tools) == len(service.default_tools())


def test_deep_agent_injects_selected_skill_into_messages():
    service = DeepAgentService.__new__(DeepAgentService)
    service.skill_registry = FakeRegistry()

    messages, bundle = service._build_messages("please analyze this paper", "session-1")

    assert [message.content for message in messages] == ["Analyze paper", "base context"]
    assert bundle.trace["selected_skill"]["name"] == "paper-analyzer"
    assert bundle.trace["selected_skill"]["enabled_tools"] == ["retrieve_knowledge", "web_search"]
    assert bundle.trace["selected_skill"]["disabled_tools"] == ["web_search"]


def test_deep_agent_keeps_messages_when_no_skill_matches():
    service = DeepAgentService.__new__(DeepAgentService)
    service.skill_registry = FakeRegistry()

    messages, bundle = service._build_messages("hello", "session-1")

    assert [message.content for message in messages] == ["base context"]
    assert bundle.trace["selected_skill"] is None
