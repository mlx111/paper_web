from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


DEFAULT_TIMEZONE = "Asia/Shanghai"
MAX_WEB_SNIPPET_CHARS = 320

MCP_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "mypaper_retrieve_knowledge": {
        "internal_tool_name": "retrieve_knowledge",
        "description": "Search the local mypaperweb knowledge base.",
        "required_args": ["query"],
        "defaults": {},
        "public": True,
    },
    "mypaper_web_search": {
        "internal_tool_name": "web_search",
        "description": "Search the web through the existing mypaperweb web_search tool.",
        "required_args": ["query"],
        "defaults": {"count": 5},
        "public": True,
    },
    "mypaper_get_current_time": {
        "internal_tool_name": "get_current_time",
        "description": "Get the current time for a timezone.",
        "required_args": [],
        "defaults": {"timezone": DEFAULT_TIMEZONE},
        "public": True,
    },
}
MCP_TOOL_MAP = {name: meta["internal_tool_name"] for name, meta in MCP_TOOL_REGISTRY.items()}

_WEB_NOISE_PHRASES = (
    "Open in app",
    "Sign in",
    "Write",
    "Search",
    "Listen",
    "Privacy",
    "Terms",
    "Help",
    "Status",
    "Careers",
    "Blog",
    "Text to speech",
)
_SENSITIVE_KEYS = ("api_key", "apikey", "token", "password", "secret", "authorization")


def _failure(error: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": error,
        "error_code": error_code,
        "summary": "",
        "truncated": False,
        "truncated_from": 0,
    }


def _normalize_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump()

    if isinstance(result, Mapping):
        payload = dict(result)
        return {
            "ok": bool(payload.get("ok", False)),
            "data": payload.get("data"),
            "error": str(payload.get("error", "")),
            "error_code": str(payload.get("error_code", "")),
            "summary": str(payload.get("summary", "")),
            "truncated": bool(payload.get("truncated", False)),
            "truncated_from": int(payload.get("truncated_from", 0) or 0),
        }

    return {
        "ok": True,
        "data": result,
        "error": "",
        "error_code": "",
        "summary": str(result)[:200],
        "truncated": False,
        "truncated_from": 0,
    }


def _get_wrapper(internal_tool_name: str):
    from tools.registry_factory import build_tool_registry
    from tools.tool_wrapper import ToolWrapper

    return ToolWrapper(build_tool_registry([internal_tool_name]))


def _get_trace_service():
    from services.run_trace_service import default_run_trace_service

    return default_run_trace_service


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(pattern in str(key).lower() for pattern in _SENSITIVE_KEYS):
                redacted[str(key)] = "***"
            else:
                redacted[str(key)] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return len(str(value))


def _attach_trace(payload: dict[str, Any], trace_run: Any | None) -> dict[str, Any]:
    if trace_run is None:
        return payload
    next_payload = dict(payload)
    next_payload["trace"] = {
        "run_id": trace_run.run_id,
        "trace_path": str(trace_run.trace_path),
    }
    return next_payload


def _trace_output(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(payload.get("ok", False)),
        "summary": str(payload.get("summary", "")),
        "error": str(payload.get("error", "")),
        "error_code": str(payload.get("error_code", "")),
        "data_size": _json_size(payload.get("data")),
        "truncated": bool(payload.get("truncated", False)),
        "truncated_from": int(payload.get("truncated_from", 0) or 0),
    }


def _start_mcp_trace(
    trace_service: Any,
    tool_name: str,
    internal_tool_name: str,
    args: dict[str, Any],
):
    return trace_service.start_run(
        session_id="mcp",
        route="mcp",
        question=f"{tool_name}({json.dumps(_redact_sensitive(args), ensure_ascii=False, default=str)})",
        metadata={
            "source": "mcp",
            "mcp_tool_name": tool_name,
            "internal_tool_name": internal_tool_name,
        },
    )


def _require_query(tool_name: str, args: dict[str, Any]) -> str | None:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return f"{tool_name}.query must be a non-empty string"
    args["query"] = query.strip()
    return None


def _validate_args(tool_name: str, args: dict[str, Any]) -> str | None:
    if tool_name == "mypaper_retrieve_knowledge":
        return _require_query(tool_name, args)

    if tool_name == "mypaper_web_search":
        query_error = _require_query(tool_name, args)
        if query_error:
            return query_error
        try:
            count = int(args.get("count", 5))
        except (TypeError, ValueError):
            return "mypaper_web_search.count must be an integer between 1 and 10"
        if count < 1 or count > 10:
            return "mypaper_web_search.count must be between 1 and 10"
        args["count"] = count
        return None

    if tool_name == "mypaper_get_current_time":
        timezone = args.get("timezone", DEFAULT_TIMEZONE)
        if not isinstance(timezone, str) or not timezone.strip():
            timezone = DEFAULT_TIMEZONE
        args["timezone"] = timezone.strip()
        return None

    return None


def _clean_snippet(text: str, max_chars: int = MAX_WEB_SNIPPET_CHARS) -> str:
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", str(text or ""))
    cleaned = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"[#*_`>]+", " ", cleaned)
    for phrase in _WEB_NOISE_PHRASES:
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .|-")
    if len(cleaned) > max_chars:
        return cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def _clean_web_search_payload(data: Mapping[str, Any]) -> dict[str, Any]:
    cleaned_data = dict(data)
    raw_results = data.get("results", [])
    cleaned_results: list[dict[str, Any]] = []

    if isinstance(raw_results, list):
        for item in raw_results:
            if not isinstance(item, Mapping):
                continue
            cleaned_results.append({
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "snippet": _clean_snippet(str(item.get("snippet", ""))),
                "source": str(item.get("source", "web")),
            })

    cleaned_data["results"] = cleaned_results
    return cleaned_data


def _postprocess_payload(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_name != "mypaper_web_search" or not payload.get("ok"):
        return payload

    data = payload.get("data")
    if not isinstance(data, Mapping):
        return payload

    next_payload = dict(payload)
    cleaned_data = _clean_web_search_payload(data)
    provider = cleaned_data.get("_provider") or "unknown"
    result_count = len(cleaned_data.get("results", [])) if isinstance(cleaned_data.get("results"), list) else 0
    plural = "" if result_count == 1 else "s"
    next_payload["data"] = cleaned_data
    next_payload["summary"] = f"Found {result_count} web search result{plural}, provider={provider}"
    return next_payload


def call_mcp_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    trace_enabled: bool = True,
    trace_service: Any = None,
) -> dict[str, Any]:
    normalized_args = dict(args or {})
    internal_tool_name = MCP_TOOL_MAP.get(tool_name, "")
    active_trace_service = trace_service if trace_service is not None else (_get_trace_service() if trace_enabled else None)
    trace_run = None
    trace_step = None

    if active_trace_service is not None:
        trace_run = _start_mcp_trace(active_trace_service, tool_name, internal_tool_name or "unknown", normalized_args)
        trace_step = active_trace_service.step(trace_run.run_id, f"mcp:{tool_name}", "mcp_tool")
        trace_step.__enter__()
        trace_step.set_input({
            "mcp_tool_name": tool_name,
            "internal_tool_name": internal_tool_name or "unknown",
            "arguments": _redact_sensitive(normalized_args),
        })

    try:
        if not internal_tool_name:
            payload = _failure(f"Unknown MCP tool: {tool_name}", "UNKNOWN_TOOL")
            if trace_step is not None:
                trace_step.set_output(_trace_output(payload))
                trace_step.mark_failed(payload["error"])
            if active_trace_service is not None and trace_run is not None:
                active_trace_service.end_run(trace_run.run_id, status="failed", error=payload["error"])
            return _attach_trace(payload, trace_run)

        validation_error = _validate_args(tool_name, normalized_args)
        if validation_error:
            payload = _failure(validation_error, "INVALID_ARGS")
            if trace_step is not None:
                trace_step.set_input({
                    "mcp_tool_name": tool_name,
                    "internal_tool_name": internal_tool_name,
                    "arguments": _redact_sensitive(normalized_args),
                })
                trace_step.set_output(_trace_output(payload))
                trace_step.mark_failed(payload["error"])
            if active_trace_service is not None and trace_run is not None:
                active_trace_service.end_run(trace_run.run_id, status="failed", error=payload["error"])
            return _attach_trace(payload, trace_run)

        try:
            result = _get_wrapper(internal_tool_name).execute(internal_tool_name, normalized_args)
            payload = _postprocess_payload(tool_name, _normalize_result(result))
        except Exception as exc:
            payload = _failure(str(exc), "TOOL_EXECUTION_ERROR")

        if trace_step is not None:
            trace_step.set_input({
                "mcp_tool_name": tool_name,
                "internal_tool_name": internal_tool_name,
                "arguments": _redact_sensitive(normalized_args),
            })
            trace_step.set_output(_trace_output(payload))
            if not payload.get("ok"):
                trace_step.mark_failed(payload.get("error") or payload.get("error_code") or "MCP tool failed")

        if active_trace_service is not None and trace_run is not None:
            if payload.get("ok"):
                active_trace_service.end_run(trace_run.run_id, status="completed")
            else:
                active_trace_service.end_run(
                    trace_run.run_id,
                    status="failed",
                    error=payload.get("error") or payload.get("error_code") or "MCP tool failed",
                )

        return _attach_trace(payload, trace_run)
    finally:
        if trace_step is not None:
            trace_step.__exit__(None, None, None)
