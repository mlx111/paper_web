"""Regression coverage for applying saved LLM settings to research workflows.

Run separately from the legacy research tests, which replace third-party modules
in sys.modules during collection. All model calls here stay local.
"""

import asyncio
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class ResearchLlmConfigReloadTest(unittest.TestCase):
    def setUp(self):
        from langchain_core.messages import AIMessage
        from langchain_core.runnables import Runnable, RunnableLambda
        from services.llm_config_service import LLMConfigService
        import services.llm_config_service as config_module
        import models.factory as factory_module

        self.real_model_class = factory_module.UniversalChatOpenAI

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = LLMConfigService()
        self.config._cache = {"active_provider": "custom", "providers": {}}
        for name, value in (
            ("_DATA_DIR", root),
            ("_CONFIG_PATH", root / "llm_config.json"),
            ("_SECRET_PATH", root / ".llm_secret"),
            ("llm_config_service", self.config),
        ):
            p = patch.object(config_module, name, value)
            p.start()
            self.addCleanup(p.stop)

        self.created = []
        created = self.created

        class LocalChatModel(Runnable):
            def __init__(self, **params):
                self.params = params
                created.append(self)

            def invoke(self, messages, config=None, **kwargs):
                import json

                return AIMessage(content=json.dumps({
                    "requires_research": False, "answer": self.params["model"],
                }))

            def bind_tools(self, tools):
                return RunnableLambda(lambda messages: self.params["model"])

        p = patch.object(factory_module, "UniversalChatOpenAI", LocalChatModel)
        p.start()
        self.addCleanup(p.stop)
        for name in ("create_llm_http_client", "create_llm_async_http_client"):
            p = patch.object(factory_module, name, return_value=None)
            p.start()
            self.addCleanup(p.stop)

        self.config.update_config(
            provider="custom", model="old-model",
            base_url="https://old.example/v1", api_key="old-test-key",
        )
        module = importlib.import_module("agents.research_workflow_service")
        self.service = module.ResearchWorkflowService(streaming=True)
        self.service.artifact_root = root / "research"
        self.service.history_root = root / "history"

    def test_reset_refreshes_all_model_bindings_and_preserves_checkpoints(self):
        service = self.service
        old_bindings = [getattr(service, name) for name in (
            "model", "decision_llm", "clarify_llm", "agent_llm", "judge_llm",
        )]
        workflow = service.workflow
        app = service._app = object()
        checkpointer = service._checkpointer = object()
        saver_cm = service._saver_cm = object()
        self.config.update_config(
            provider="custom", model="new-model",
            base_url="https://new.example/v1", api_key="new-test-key",
        )

        service.reset_agent()

        for name, old in zip(
            ("model", "decision_llm", "clarify_llm", "agent_llm", "judge_llm"), old_bindings,
        ):
            self.assertIsNot(getattr(service, name), old)
        self.assertEqual(service.model.params["model"], "new-model")
        self.assertEqual(service.model.params["base_url"], "https://new.example/v1")
        self.assertEqual(service.model.params["api_key"].get_secret_value(), "new-test-key")
        self.assertTrue(service.model.params["streaming"])
        self.assertIs(service.workflow, workflow)
        self.assertIs(service._app, app)
        self.assertIs(service._checkpointer, checkpointer)
        self.assertIs(service._saver_cm, saver_cm)

    def test_saving_settings_updates_model_used_by_existing_compiled_graph(self):
        service = self.service
        graph = service.workflow.compile()
        from langchain_core.messages import HumanMessage

        async def answer():
            result = await graph.ainvoke({"messages": [HumanMessage(content="hello")]})
            return result["messages"][-1].content

        self.assertEqual(asyncio.run(answer()), "old-model")
        stubs = {}
        for name in ("quick", "deep", "multi", "file"):
            attr = f"{name}_agent_service"
            stubs[f"agents.{attr}"] = types.SimpleNamespace(**{attr: Mock()})
        stubs["agents.research_workflow_service"] = types.SimpleNamespace(
            research_workflow_service=service,
        )
        stubs["evaluation"] = types.SimpleNamespace(dispatcher=types.SimpleNamespace(
            _simple_quick_agent=object(),
        ))
        with patch.dict(sys.modules, stubs):
            from routers.llm_config import LLMConfigBody, update_llm_config

            update_llm_config(LLMConfigBody(
                provider="custom", model="new-model",
                base_url="https://new.example/v1", api_key="new-test-key",
            ))

        self.assertEqual(asyncio.run(answer()), "new-model")
        self.assertEqual(service.model.params["base_url"], "https://new.example/v1")
        self.assertEqual(service.model.params["api_key"].get_secret_value(), "new-test-key")

    def test_control_nodes_send_json_prompt_without_forced_tools_in_thinking_mode(self):
        import json
        import httpx
        from langchain_core.messages import HumanMessage
        from agents import research_workflow_service as research_module

        replies = [
            {"requires_research": True, "answer": None},
            {"needs_clarification": True, "candidates": [{
                "candidate_id": "A", "title": "Agents", "core_question": "How?",
                "expected_output": "Review", "search_keywords": "agents",
            }], "questions": [], "assumed_scope": "Agents", "refined_query": "Agents"},
            {"is_good_answer": True, "feedback": None},
        ]
        requests = []

        def respond(request):
            body = json.loads(request.content)
            reply = json.dumps(replies[len(requests) % len(replies)])
            requests.append(body)
            response = {
                "id": "local-test", "object": "chat.completion", "created": 0,
                "model": "qwen3.5-flash", "choices": [{
                    "index": 0, "finish_reason": "stop", "message": {
                        "role": "assistant", "content": reply,
                        "reasoning_content": "Local reasoning.",
                    },
                }],
            }
            if body["stream"]:
                deltas = [
                    {"role": "assistant", "reasoning_content": "Local reasoning."},
                    {"content": reply[:len(reply) // 2]},
                    {"content": reply[len(reply) // 2:]},
                    {},
                ]
                chunks = [json.dumps({**response, "object": "chat.completion.chunk", "choices": [{
                    "index": 0, "delta": delta, "finish_reason": "stop" if not delta else None,
                }]}) for delta in deltas]
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"},
                    text="".join(f"data: {chunk}\n\n" for chunk in chunks) + "data: [DONE]\n\n",
                )
            return httpx.Response(200, json=response)

        results = []
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            for streaming in (False, True):
                model = self.real_model_class(
                    model="qwen3.5-flash", base_url="https://example.test/v1",
                    api_key="local-test", extra_body={"enable_thinking": True}, streaming=streaming,
                    http_client=client,
                )
                with patch.object(research_module.qwen_model, "init_model", return_value=model):
                    self.service.reset_agent()
                results.extend([
                    getattr(self.service, name).invoke([HumanMessage(content="Research agents")])
                    for name in ("decision_llm", "clarify_llm", "judge_llm")
                ])

        for body in requests:
            self.assertNotIn("tools", body)
            self.assertNotIn("tool_choice", body)
            self.assertNotIn("response_format", body)
            self.assertTrue(body["enable_thinking"])
            self.assertIn("JSON", body["messages"][0]["content"])
        self.assertEqual(len(requests), 6)
        for offset in (0, 3):
            self.assertTrue(results[offset].requires_research)
            self.assertEqual(results[offset + 1].candidates[0].candidate_id, "A")
            self.assertTrue(results[offset + 2].is_good_answer)


if __name__ == "__main__":
    unittest.main()
