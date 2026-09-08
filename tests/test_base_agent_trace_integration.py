import asyncio
import sys
import types
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
    def __init__(self, content=""):
        self.content = content


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
sys.modules["utils.notes"].get_memory_writer = lambda: None
sys.modules["utils.notes"].select_relevant_memories = lambda *args, **kwargs: []
sys.modules["utils.rag_utils"].rag_utils_service = types.SimpleNamespace()

from agents.Base_agent_service import BaseAgentService
from services.run_trace_service import RunTraceService


class AIMessageChunk:
    content_blocks = [{"type": "text", "text": "hello"}]
    tool_calls = []
    usage_metadata = None
    response_metadata = {}


class _FakeAgent:
    async def astream(self, input, stream_mode):
        yield AIMessageChunk(), {"langgraph_node": "agent"}


class _TestAgentService(BaseAgentService):
    def get_system_prompt_file(self) -> str:
        return "unused.txt"

    def build_agent(self):
        return _FakeAgent()


def test_stream_query_records_trace_and_exposes_run_id(tmp_path):
    service = _TestAgentService.__new__(_TestAgentService)
    service.__class__.context_mode = "deep"
    service._agent_initialized = True
    service.agent = _FakeAgent()
    service.run_trace_service = RunTraceService(base_dir=tmp_path)
    service._save_turn = lambda session_id, question, answer: None
    service._persist_memory = lambda session_id, question, answer: None

    bundle = types.SimpleNamespace(
        mode="deep",
        routing_hints=["rag"],
        trace={"candidate_count": 2},
    )
    service._build_messages = lambda question, session_id: ([_Message(question)], bundle)

    async def _collect():
        return [
            event
            async for event in service.query_stream(
                question="what is agentic rag?",
                session_id="session-1",
            )
        ]

    events = asyncio.run(_collect())

    context_event = events[0]
    run_id = context_event["data"]["run_id"]
    trace = service.run_trace_service.load_run(run_id)

    assert context_event["type"] == "context"
    assert context_event["data"]["trace_path"].endswith(f"{run_id}.json")
    assert trace["status"] == "completed"
    assert [step["step_name"] for step in trace["steps"]] == ["context_build", "model_stream"]
    assert trace["steps"][0]["output"]["context_mode"] == "deep"
    assert trace["steps"][1]["output"]["answer_chars"] == 5
    assert trace["steps"][1]["output"]["token_usage"]["total_tokens"] > 0
    assert trace["steps"][1]["output"]["token_usage"]["estimated"] is True


def test_stream_query_prefers_model_usage_metadata(tmp_path):
    class UsageChunk:
        content_blocks = [{"type": "text", "text": "hello"}]
        tool_calls = []
        usage_metadata = {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        }
        response_metadata = {}

    class UsageAgent:
        async def astream(self, input, stream_mode):
            yield UsageChunk(), {"langgraph_node": "agent"}

    service = _TestAgentService.__new__(_TestAgentService)
    service.__class__.context_mode = "deep"
    service._agent_initialized = True
    service.agent = UsageAgent()
    service.run_trace_service = RunTraceService(base_dir=tmp_path)
    service._save_turn = lambda session_id, question, answer: None
    service._persist_memory = lambda session_id, question, answer: None

    bundle = types.SimpleNamespace(
        mode="deep",
        routing_hints=[],
        trace={},
    )
    service._build_messages = lambda question, session_id: ([_Message(question)], bundle)

    async def _collect():
        return [
            event
            async for event in service.query_stream(
                question="what is agentic rag?",
                session_id="session-1",
            )
        ]

    events = asyncio.run(_collect())
    run_id = events[0]["data"]["run_id"]
    trace = service.run_trace_service.load_run(run_id)
    token_usage = trace["steps"][1]["output"]["token_usage"]

    assert token_usage == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
        "estimated": False,
        "source": "model_usage_metadata",
    }
