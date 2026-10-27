"""Regression tests for provider-neutral OpenAI-compatible model handling."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _model(**kwargs):
    from models.factory import UniversalChatOpenAI

    return UniversalChatOpenAI(
        model="deepseek-flash",
        api_key="test-key",
        base_url="https://example.test/v1",
        **kwargs,
    )


def test_thinking_reasoning_content_is_added_to_follow_up_request():
    model = _model(preserve_reasoning_content=True)
    payload = model._get_request_payload(
        [
            HumanMessage(content="question"),
            AIMessage(content="answer", additional_kwargs={"reasoning_content": "think"}),
        ]
    )

    assert payload["messages"][-1]["reasoning_content"] == "think"


def test_non_thinking_provider_does_not_receive_reasoning_content():
    model = _model(preserve_reasoning_content=False)
    payload = model._get_request_payload(
        [
            HumanMessage(content="question"),
            AIMessage(content="answer", additional_kwargs={"reasoning_content": "think"}),
        ]
    )

    assert "reasoning_content" not in payload["messages"][-1]


def test_empty_reasoning_field_is_preserved_for_tool_protocol():
    model = _model(preserve_reasoning_content=True)
    payload = model._get_request_payload(
        [HumanMessage(content="question"), AIMessage(content="", additional_kwargs={"reasoning_content": ""})]
    )

    assert payload["messages"][-1]["reasoning_content"] == ""


def test_reasoning_content_from_provider_response_is_kept_on_ai_message():
    model = _model(preserve_reasoning_content=True)
    result = model._create_chat_result(
        {
            "model": "deepseek-flash",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "answer",
                        "reasoning_content": "think",
                    },
                }
            ],
        }
    )

    assert result.generations[0].message.additional_kwargs["reasoning_content"] == "think"


def test_streamed_tool_call_round_trip_preserves_reasoning_and_tool_id():
    import json

    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            deltas = [
                {"role": "assistant", "reasoning_content": "think"},
                {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "search", "arguments": "{}"}}]},
            ]
            finish_reason = "tool_calls"
        else:
            deltas = [{"role": "assistant"}, {"content": "done"}]
            finish_reason = "stop"
        events = [
            {"id": "local-test", "object": "chat.completion.chunk", "created": 0,
             "model": "deepseek-flash", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
            for delta in deltas
        ]
        events.append({"id": "local-test", "object": "chat.completion.chunk", "created": 0,
                       "model": "deepseek-flash", "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text="".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = _model(preserve_reasoning_content=True, streaming=True, http_client=client)
        first = model.bind_tools([{"type": "function", "function": {"name": "search", "description": "Search", "parameters": {"type": "object", "properties": {}}}}]).invoke([HumanMessage(content="find")])
        assert first.tool_calls[0]["id"] == "call-1"
        assert first.additional_kwargs["reasoning_content"] == "think"
        from langchain_core.messages import ToolMessage

        model.invoke([HumanMessage(content="find"), first, ToolMessage(content="result", tool_call_id="call-1")])

    assert requests[1]["messages"][1]["reasoning_content"] == "think"
    assert requests[1]["messages"][1]["tool_calls"][0]["id"] == "call-1"


def test_message_metadata_clone_keeps_reasoning_and_tool_protocol_fields():
    from utils.message_compat import clone_ai_message

    original = AIMessage(
        content="old",
        name="agent",
        id="msg-1",
        additional_kwargs={"reasoning_content": "think", "custom": "value"},
        response_metadata={"model_name": "deepseek-flash"},
        tool_calls=[{"id": "call-1", "name": "search", "args": {}, "type": "tool_call"}],
    )
    cloned = clone_ai_message(original, content="new", name="planning")

    assert cloned.content == "new"
    assert cloned.name == "planning"
    assert cloned.additional_kwargs["reasoning_content"] == "think"
    assert cloned.response_metadata["model_name"] == "deepseek-flash"
    assert cloned.tool_calls[0]["id"] == "call-1"


def test_research_messages_reclassify_synthetic_ai_notes_for_thinking_provider():
    from utils.message_compat import prepare_research_messages

    messages = [
        HumanMessage(content="question"),
        AIMessage(content="branch summary", name="branch_synthesize"),
        AIMessage(content="plan", name="planning", additional_kwargs={"reasoning_content": "think"}),
    ]
    prepared = prepare_research_messages(messages, provider="deepseek")

    assert prepared[1].type == "human"
    assert "branch summary" in prepared[1].content
    assert prepared[2].type == "ai"
    assert prepared[2].additional_kwargs["reasoning_content"] == "think"
    assert prepare_research_messages(messages, provider="openai") == messages


def test_research_messages_keep_non_thinking_tool_call_protocol_intact():
    from utils.message_compat import prepare_research_messages

    message = AIMessage(content="", tool_calls=[{"id": "call-1", "name": "search", "args": {}}])
    assert prepare_research_messages([message], provider="deepseek") == [message]


def test_research_messages_remove_incomplete_tool_call_rounds():
    from langchain_core.messages import ToolMessage
    from utils.message_compat import sanitize_tool_call_pairs

    messages = [
        HumanMessage(content="search"),
        AIMessage(content="", tool_calls=[
            {"id": "call-ok", "name": "search", "args": {}},
            {"id": "call-missing", "name": "search", "args": {}},
        ]),
        ToolMessage(content="result", tool_call_id="call-ok"),
        HumanMessage(content="continue"),
    ]

    prepared = sanitize_tool_call_pairs(messages)

    assert not any(isinstance(message, AIMessage) and message.tool_calls for message in prepared)
    assert not any(isinstance(message, ToolMessage) for message in prepared)


def test_openai_reasoning_models_do_not_receive_unsupported_temperature():
    from models.factory import UniversalModelFactory

    assert UniversalModelFactory._temperature_params("gpt-5", 0.7) == {}
    assert UniversalModelFactory._temperature_params("o3-mini", 0.7) == {}
    assert UniversalModelFactory._temperature_params("deepseek-flash", 0.7) == {"temperature": 0.7}


def test_reasoning_extension_profile_covers_compatible_provider_presets():
    from models.factory import UniversalModelFactory

    for provider in ("deepseek", "dashscope", "moonshot", "zhipu", "custom"):
        assert UniversalModelFactory._preserves_reasoning(provider)
    for provider in ("openai", "ollama"):
        assert not UniversalModelFactory._preserves_reasoning(provider)
