from __future__ import annotations

import inspect
import json
import logging
import time
from typing import Any

from .dispatcher import get_target_agent
from .failure_classifier import classify_failure
from .loader import load_cases
from .metrics import (
    calc_result_score,
    context_mode_hit,
    keyword_hit,
    must_include_hit,
    must_not_include_hit,
    notes_used_hit,
    summarize,
    tool_args_hit,
    tool_hit,
)
from .reporter import write_json_report, write_markdown_report
from .types import EvaluationCase, EvaluationResult
from services.run_trace_service import default_run_trace_service


logger = logging.getLogger(__name__)


class EvaluationRunner:
    """
    Runs evaluation cases against explicit quick/deep agents.

    Automatic routing evaluation was removed because the UI now chooses the
    target chain directly by module.
    """

    def __init__(self, cases_path: str):
        self.cases_path = cases_path

    def _estimate_tokens(self, text: str) -> int:
        text = text or ""
        return max(0, len(text) // 2)

    def _extract_tools(self, raw_result: Any) -> list[dict[str, object]]:
        """Extract tool calls with name+args from non-streaming output."""
        tool_calls: list[dict[str, object]] = []

        if isinstance(raw_result, dict):
            maybe_tools = raw_result.get("tools") or raw_result.get("tool_calls") or []
            if isinstance(maybe_tools, list):
                for item in maybe_tools:
                    if isinstance(item, str):
                        tool_calls.append({"name": item, "args": {}})
                    elif isinstance(item, dict):
                        name = item.get("name")
                        if name:
                            args = item.get("args") or item.get("arguments") or {}
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except (json.JSONDecodeError, TypeError):
                                    args = {}
                            tool_calls.append({
                                "name": str(name),
                                "args": dict(args) if isinstance(args, dict) else {},
                            })

        return tool_calls

    def _extract_tool_call_from_stream_event(self, event: dict[str, Any]) -> dict[str, object]:
        event_type = str(event.get("type", "") or "").strip().lower()
        if event_type != "tool_call":
            return {}

        data = event.get("data") or {}
        if not isinstance(data, dict):
            return {}

        tool_name = data.get("tool_name") or data.get("name") or ""
        arguments = data.get("arguments")
        if arguments is None:
            arguments = data.get("args", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {}

        return {
            "name": str(tool_name),
            "args": dict(arguments) if isinstance(arguments, dict) else {},
        }

    def _summarize_trace_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        steps = payload.get("steps") or []
        if not isinstance(steps, list):
            steps = []

        failed_steps = []
        tool_steps = []
        tool_error_codes: list[str] = []
        total_latency_ms = 0
        token_usage = 0

        for step in steps:
            if not isinstance(step, dict):
                continue

            latency = step.get("latency_ms")
            if isinstance(latency, (int, float)):
                total_latency_ms += latency

            step_type = str(step.get("step_type") or "")
            step_name = str(step.get("step_name") or "")
            if step_type.lower() == "tool" or step_name.lower().startswith("tool:"):
                tool_steps.append(step_name)

            if str(step.get("status") or "").lower() == "failed":
                failed_steps.append(
                    {
                        "step_name": step_name,
                        "step_type": step_type,
                        "error": step.get("error") or "",
                    }
                )

            token_usage += self._extract_total_tokens(step.get("output"))
            for code in self._extract_error_codes(step):
                if code not in tool_error_codes:
                    tool_error_codes.append(code)

        return {
            "trace_status": str(payload.get("status") or ""),
            "step_count": len(steps),
            "failed_steps": failed_steps,
            "tool_steps": tool_steps,
            "total_latency_ms": round(total_latency_ms, 2),
            "token_usage": token_usage,
            "tool_error_codes": tool_error_codes,
        }

    def _load_trace_summary(self, run_id: str) -> tuple[dict[str, Any], str]:
        if not run_id:
            return {}, ""
        try:
            payload = default_run_trace_service.load_run(run_id)
            return self._summarize_trace_payload(payload), ""
        except Exception as exc:
            return {}, str(exc)

    def _extract_total_tokens(self, value: Any) -> int:
        if isinstance(value, dict):
            token_usage = value.get("token_usage")
            if isinstance(token_usage, dict):
                total = token_usage.get("total_tokens")
                if isinstance(total, (int, float)):
                    return int(total)
                prompt = token_usage.get("prompt_tokens")
                completion = token_usage.get("completion_tokens")
                if isinstance(prompt, (int, float)) or isinstance(completion, (int, float)):
                    return int(prompt or 0) + int(completion or 0)
            if "total_tokens" in value and isinstance(value.get("total_tokens"), (int, float)):
                return int(value["total_tokens"])
            return sum(self._extract_total_tokens(item) for item in value.values())
        if isinstance(value, list):
            return sum(self._extract_total_tokens(item) for item in value)
        return 0

    def _extract_error_codes(self, value: Any) -> list[str]:
        codes: list[str] = []
        if isinstance(value, dict):
            error_code = value.get("error_code")
            if error_code:
                codes.append(str(error_code))
            for item in value.values():
                codes.extend(self._extract_error_codes(item))
        elif isinstance(value, list):
            for item in value:
                codes.extend(self._extract_error_codes(item))
        return codes

    async def _invoke_with_stream(self, agent: Any, question: str, session_id: str) -> tuple[str, list[str], list[dict[str, object]], dict[str, Any]]:
        answer_parts: list[str] = []
        tool_names: list[str] = []
        tool_calls: list[dict[str, object]] = []
        stream_events: list[dict[str, Any]] = []
        context_meta: dict[str, Any] = {}

        query_stream = getattr(agent, "query_stream", None)
        if callable(query_stream):
            try:
                stream_result = query_stream(question, session_id)
                if inspect.isasyncgen(stream_result) or hasattr(stream_result, "__aiter__"):
                    async for event in stream_result:
                        if not isinstance(event, dict):
                            continue

                        stream_events.append(event)
                        event_type = str(event.get("type", "") or "").strip().lower()

                        if event_type == "context":
                            data = event.get("data") or {}
                            context_meta = data if isinstance(data, dict) else {}
                            continue

                        if event_type == "content":
                            data = event.get("data", "")
                            if data:
                                answer_parts.append(str(data))
                            continue

                        if event_type == "tool_call":
                            tc = self._extract_tool_call_from_stream_event(event)
                            if tc.get("name"):
                                tool_names.append(str(tc["name"]))
                                tool_calls.append(tc)
                            continue

                        if event_type == "complete":
                            break

                    answer_text = "".join(answer_parts).strip()
                    meta = {
                        "used_streaming": True,
                        "stream_event_count": len(stream_events),
                        "tool_event_count": sum(1 for item in stream_events if str(item.get("type", "")).lower() == "tool_call"),
                        "stream_events": stream_events,
                        "context_mode": context_meta.get("context_mode", getattr(agent, "context_mode", "")),
                        "context_trace": context_meta.get("trace", {}),
                        "routing_hints": context_meta.get("routing_hints", []),
                        "tool_calls": tool_calls,
                        "run_id": str(context_meta.get("run_id") or ""),
                        "trace_path": str(context_meta.get("trace_path") or ""),
                    }
                    return answer_text, list(dict.fromkeys(tool_names)), tool_calls, meta
            except Exception as exc:
                stream_events.append({"type": "error", "error": str(exc)})

        output = await agent.query(question, session_id)
        if isinstance(output, str):
            answer_text = output
        elif isinstance(output, dict):
            answer_text = str(output.get("answer", ""))
            raw_tool_calls = self._extract_tools(output)
            for t in raw_tool_calls:
                tool_names.append(str(t["name"]))
                tool_calls.append(t)
        else:
            answer_text = str(output)

        meta = {
            "used_streaming": False,
            "stream_event_count": len(stream_events),
            "tool_event_count": 0,
            "stream_events": stream_events,
            "context_mode": getattr(agent, "context_mode", ""),
            "context_trace": {},
            "routing_hints": [],
            "tool_calls": tool_calls,
            "run_id": "",
            "trace_path": "",
        }
        return answer_text, list(dict.fromkeys(tool_names)), tool_calls, meta

    async def _run_one(self, case: EvaluationCase) -> EvaluationResult:
        agent = get_target_agent(case.mode)

        start = time.perf_counter()
        error = ""
        answer_text = ""
        mode = (case.mode or "").strip().lower()
        actual_route = mode if mode in ("quick", "deep") else "deep"
        actual_tools: list[str] = []
        run_meta: dict[str, Any] = {}

        try:
            answer_text, actual_tools, actual_tool_calls, stream_meta = await self._invoke_with_stream(agent, case.question, case.id)
            run_meta.update(stream_meta)
        except Exception as exc:
            error = str(exc)
            actual_tool_calls = []

        latency_ms = (time.perf_counter() - start) * 1000.0
        run_id = str(run_meta.get("run_id") or "")
        trace_path = str(run_meta.get("trace_path") or "")
        trace_summary, trace_load_error = self._load_trace_summary(run_id)
        if trace_load_error:
            run_meta["trace_load_error"] = trace_load_error

        actual_context_mode = str(run_meta.get("context_mode", "") or "")
        context_trace = run_meta.get("context_trace") or {}
        actual_notes_used = False
        if isinstance(context_trace, dict):
            actual_notes_used = int(context_trace.get("note_count", 0) or 0) > 0

        expected_context_mode = case.expected_context_mode or actual_route
        expected_route = (case.expected_route or actual_route).strip().lower()
        route_correct = actual_route == expected_route
        tool_correct = tool_hit(actual_tools, case.expected_tools)
        tool_args_correct = tool_args_hit(actual_tool_calls, case.expected_tool_args)
        if case.expected_tool_args and not tool_args_correct:
            logger.warning(
                "tool args not matched: case=%s, expected=%s, actual=%s",
                case.id,
                case.expected_tool_args,
                actual_tool_calls,
            )
        kw_hit = keyword_hit(answer_text, case.expected_keywords)
        ev_hit = keyword_hit(answer_text, case.expected_evidence)
        include_hit = must_include_hit(answer_text, case.must_include)
        exclude_hit = must_not_include_hit(answer_text, case.must_not_include)
        notes_hit = notes_used_hit(actual_notes_used, case.expected_notes_used)
        context_mode_correct = context_mode_hit(actual_context_mode, expected_context_mode)

        estimated_token_usage = self._estimate_tokens(answer_text) + self._estimate_tokens(json.dumps(run_meta, ensure_ascii=False))
        trace_token_usage = int(trace_summary.get("token_usage") or 0) if trace_summary else 0

        result = EvaluationResult(
            case_id=case.id,
            question=case.question,
            mode=case.mode,
            expected_route=case.expected_route,
            actual_route=actual_route,
            expected_tools=case.expected_tools,
            actual_tools=actual_tools,
            answer_text=answer_text,
            latency_ms=round(latency_ms, 2),
            token_usage=trace_token_usage or estimated_token_usage,
            route_correct=route_correct,
            tool_correct=tool_correct,
            tool_args_correct=tool_args_correct,
            keyword_hit=kw_hit,
            evidence_hit=ev_hit,
            must_include_hit=include_hit,
            must_not_include_hit=exclude_hit,
            notes_used=notes_hit,
            context_mode_correct=context_mode_correct,
            actual_context_mode=actual_context_mode,
            error=error,
            run_id=run_id,
            trace_path=trace_path,
            trace_summary=trace_summary,
            meta={
                "difficulty": case.difficulty,
                "expected_answer_type": case.expected_answer_type,
                "extra": case.extra,
                "expected_context_mode": expected_context_mode,
                "expected_notes_used": case.expected_notes_used,
                "actual_notes_used": actual_notes_used,
                **run_meta,
            },
        )
        result.score = calc_result_score(result)
        result.failure_category, result.failure_reason = classify_failure(case, result)
        return result

    async def run(self) -> tuple[list[EvaluationResult], Any]:
        cases = load_cases(self.cases_path)
        results: list[EvaluationResult] = []

        for case in cases:
            result = await self._run_one(case)
            results.append(result)

        summary = summarize(results)
        return results, summary

    async def run_and_report(self, json_report_path: str, md_report_path: str) -> None:
        results, summary = await self.run()
        write_json_report(json_report_path, summary, results)
        write_markdown_report(md_report_path, summary, results)
