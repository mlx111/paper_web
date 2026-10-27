"""Message helpers shared by provider adapters and workflow boundaries."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


def clone_ai_message(
    message: AIMessage,
    *,
    content: Any | None = None,
    name: str | None = None,
) -> AIMessage:
    """Copy an AI message without dropping provider protocol metadata.

    LangGraph workflows often create a new message after extracting text.  A
    shallow ``AIMessage(content=...)`` loses reasoning content, tool call ids,
    usage metadata, and response metadata that an OpenAI-compatible provider
    may require on the next request.
    """

    return AIMessage(
        content=message.content if content is None else content,
        name=message.name if name is None else name,
        id=message.id,
        additional_kwargs=dict(message.additional_kwargs or {}),
        response_metadata=dict(message.response_metadata or {}),
        usage_metadata=dict(message.usage_metadata) if message.usage_metadata else None,
        tool_calls=[dict(call) for call in (message.tool_calls or [])],
        invalid_tool_calls=[dict(call) for call in (message.invalid_tool_calls or [])],
    )


def sanitize_tool_call_pairs(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Keep only assistant tool-call rounds with every result immediately after.

    OpenAI-compatible APIs reject a history when an assistant message contains
    ``tool_calls`` without one following ``ToolMessage`` for each call.  This
    can happen after a cancelled run, a checkpoint resume, or context
    compression.  Incomplete rounds are removed before any provider sees the
    history.
    """

    cleaned: list[BaseMessage] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        tool_calls = list(getattr(message, "tool_calls", []) or []) if isinstance(message, AIMessage) else []
        if not tool_calls:
            if isinstance(message, ToolMessage):
                # A tool result is valid only when the immediately preceding
                # message is the assistant call round that owns its id.
                if not cleaned or not isinstance(cleaned[-1], AIMessage):
                    index += 1
                    continue
                owner_ids = {call.get("id") for call in getattr(cleaned[-1], "tool_calls", []) or []}
                if getattr(message, "tool_call_id", "") not in owner_ids:
                    index += 1
                    continue
            cleaned.append(message)
            index += 1
            continue

        expected_ids = [call.get("id") for call in tool_calls if call.get("id")]
        following: list[ToolMessage] = []
        cursor = index + 1
        while cursor < len(messages) and isinstance(messages[cursor], ToolMessage):
            following.append(messages[cursor])
            cursor += 1
        result_ids = [getattr(item, "tool_call_id", "") for item in following]
        complete = bool(expected_ids) and len(expected_ids) == len(tool_calls) and set(expected_ids) <= set(result_ids)
        if complete:
            cleaned.append(message)
            cleaned.extend(item for item in following if getattr(item, "tool_call_id", "") in set(expected_ids))
        elif getattr(message, "content", ""):
            preserved = clone_ai_message(message, content=message.content)
            preserved.tool_calls = []
            cleaned.append(preserved)
        # Drop the incomplete round and its contiguous results.
        index = cursor if following else index + 1

    return cleaned


def prepare_research_messages(messages: list[BaseMessage], *, provider: str) -> list[BaseMessage]:
    """Send synthetic workflow notes as context in DeepSeek thinking mode.

    Those notes were created by application code and never had a matching
    thinking trace. A genuine tool-call reply is kept intact because DeepSeek
    also offers non-thinking tool calls that have no reasoning trace.
    """

    if provider not in {"deepseek", "dashscope", "moonshot", "zhipu", "custom"}:
        return messages

    prepared: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, AIMessage) and "reasoning_content" not in message.additional_kwargs:
            if message.tool_calls:
                prepared.append(message)
                continue
            if message.content:
                prepared.append(HumanMessage(content=f"Previous workflow context (data): {message.content}"))
        else:
            prepared.append(message)
    return prepared
