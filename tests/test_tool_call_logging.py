import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

for name in [
    "langchain_core",
    "langchain_core.messages",
    "langgraph",
    "langgraph.store",
    "langgraph.store.memory",
    "loguru",
    "context",
    "context.builder",
    "context.context_config",
    "models",
    "models.factory",
    "settings",
    "settings.config",
    "utils",
    "utils.history",
    "utils.notes",
    "utils.rag_utils",
]:
    sys.modules.setdefault(name, types.ModuleType(name))


class _Message:
    pass


sys.modules["langchain_core.messages"].AIMessage = _Message
sys.modules["langchain_core.messages"].HumanMessage = _Message
sys.modules["langchain_core.messages"].SystemMessage = _Message
sys.modules["langgraph.store.memory"].InMemoryStore = object
sys.modules["loguru"].logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)
sys.modules["context.builder"].ContextBuilder = object
sys.modules["context.context_config"].ContextConfig = object
sys.modules["models.factory"].qwen_model = types.SimpleNamespace(init_model=lambda streaming: None)
sys.modules["settings.config"].config = types.SimpleNamespace(rag_model="test")
sys.modules["utils.history"].get_history = lambda session_id: None
sys.modules["utils.notes"].save_high_value_note = lambda **kwargs: None
sys.modules["utils.rag_utils"].rag_utils_service = types.SimpleNamespace()

from agents.Base_agent_service import BaseAgentService


class _ToolMessage:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class ToolCallLoggingTest(unittest.TestCase):
    def test_extracts_tool_names_from_all_messages(self):
        messages = [
            _ToolMessage([{"name": "web_search"}, {"name": "get_current_time"}]),
            _ToolMessage([{"name": "web_search"}]),
            _ToolMessage([]),
        ]

        self.assertEqual(
            BaseAgentService._extract_tool_names(messages),
            ["web_search", "get_current_time"],
        )


if __name__ == "__main__":
    unittest.main()
