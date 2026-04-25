from __future__ import annotations

import inspect
import json
import time
from typing import Any

from agents.deep_agent_service import deep_agent_service
from agents.quick_agent_service import quick_agent_service
from agents.router_agent_service import agent_service as router_agent_service

from .dispatcher import get_target_agent
from .loader import load_cases
from .metrics import (
    calc_result_score,
    context_mode_hit,
    keyword_hit,
    must_include_hit,
    must_not_include_hit,
    notes_used_hit,
    summarize,
    tool_hit,
)
from .reporter import write_json_report, write_markdown_report
from .types import EvaluationCase, EvaluationResult


class EvaluationRunner:
    """
    评估跑批器。

    负责把测试集逐条送进被测 agent，
    并收集流式输出、tool_calls、路由决策、上下文元信息、耗时和评分。
    """

    def __init__(self, cases_path: str):
        self.cases_path = cases_path

    def _estimate_tokens(self, text: str) -> int:
        """
        用字符数粗略估算 token 数。
        """
        text = text or ""
        return max(0, len(text) // 2)

    def _extract_tools(self, raw_result: Any) -> list[str]:
        """
        从非流式结果中提取工具名。
        """
        tools: list[str] = []

        if isinstance(raw_result, dict):
            maybe_tools = raw_result.get("tools") or raw_result.get("tool_calls") or []
            if isinstance(maybe_tools, list):
                for item in maybe_tools:
                    if isinstance(item, str):
                        tools.append(item)
                    elif isinstance(item, dict):
                        name = item.get("name")
                        if name:
                            tools.append(str(name))

        return list(dict.fromkeys(tools))

    def _extract_tools_from_stream_event(self, event: dict[str, Any]) -> list[str]:
        """
        从流式事件里提取工具调用名称。
        """
        tools: list[str] = []
        event_type = str(event.get("type", "") or "").strip().lower()
        if event_type != "tool_call":
            return tools

        data = event.get("data") or {}
        if isinstance(data, dict):
            tool_name = data.get("tool_name") or data.get("name")
            if tool_name:
                tools.append(str(tool_name))

        return tools

    async def _invoke_with_stream(self, agent: Any, question: str, session_id: str) -> tuple[str, list[str], dict[str, Any]]:
        """
        优先走流式接口，边生成边收集 tool_calls 和 context meta。
        """
        answer_parts: list[str] = []
        tool_names: list[str] = []
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
                            context_meta = event.get("data") or {}
                            continue

                        if event_type == "content":
                            data = event.get("data", "")
                            if data:
                                answer_parts.append(str(data))
                            continue

                        if event_type == "tool_call":
                            tool_names.extend(self._extract_tools_from_stream_event(event))
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
                    }
                    return answer_text, list(dict.fromkeys(tool_names)), meta
            except Exception as exc:
                stream_events.append({"type": "error", "error": str(exc)})

        output = await agent.query(question, session_id)
        if isinstance(output, str):
            answer_text = output
        elif isinstance(output, dict):
            answer_text = str(output.get("answer", ""))
            tool_names.extend(self._extract_tools(output))
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
        }
        return answer_text, list(dict.fromkeys(tool_names)), meta

    async def _resolve_router_route(self, question: str, session_id: str) -> tuple[str, dict[str, Any]]:
        """
        Router 模式下，先单独拿到路由决策。
        """
        decision = await router_agent_service.route_query(question, session_id)
        route = getattr(decision, "route", "") or ""
        route = str(route).strip().lower()
        if route not in ("quick", "deep"):
            route = "deep"

        reason = getattr(decision, "reason", "")
        if hasattr(decision, "model_dump"):
            decision_payload = decision.model_dump()
        elif hasattr(decision, "dict"):
            decision_payload = decision.dict()
        else:
            decision_payload = {"route": route, "reason": reason}

        return route, {
            "router_reason": reason,
            "router_decision": decision_payload,
            "context_mode": "router",
            "context_trace": {},
            "routing_hints": [],
        }

    async def _run_one(self, case: EvaluationCase) -> EvaluationResult:
        """
        跑单条 case。
        """
        agent = get_target_agent(case.mode)

        start = time.perf_counter()
        error = ""
        answer_text = ""
        actual_route = ""
        actual_tools: list[str] = []
        run_meta: dict[str, Any] = {}

        try:
            if case.mode == "router":
                actual_route, run_meta = await self._resolve_router_route(case.question, case.id)
                agent = quick_agent_service if actual_route == "quick" else deep_agent_service
            else:
                actual_route = case.expected_route

            answer_text, actual_tools, stream_meta = await self._invoke_with_stream(agent, case.question, case.id)
            run_meta.update(stream_meta)

        except Exception as exc:
            error = str(exc)

        latency_ms = (time.perf_counter() - start) * 1000.0

        if not actual_route:
            actual_route = case.expected_route

        actual_context_mode = str(run_meta.get("context_mode", "") or "")
        context_trace = run_meta.get("context_trace") or {}
        actual_notes_used = False
        if isinstance(context_trace, dict):
            actual_notes_used = int(context_trace.get("note_count", 0) or 0) > 0

        expected_context_mode = case.expected_context_mode or case.mode
        route_correct = actual_route.strip().lower() == case.expected_route.strip().lower()
        tool_correct = tool_hit(actual_tools, case.expected_tools)
        kw_hit = keyword_hit(answer_text, case.expected_keywords)
        ev_hit = keyword_hit(answer_text, case.expected_evidence)
        include_hit = must_include_hit(answer_text, case.must_include)
        exclude_hit = must_not_include_hit(answer_text, case.must_not_include)
        notes_hit = notes_used_hit(actual_notes_used, case.expected_notes_used)
        context_mode_correct = context_mode_hit(actual_context_mode, expected_context_mode)

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
            token_usage=self._estimate_tokens(answer_text) + self._estimate_tokens(json.dumps(run_meta, ensure_ascii=False)),
            route_correct=route_correct,
            tool_correct=tool_correct,
            keyword_hit=kw_hit,
            evidence_hit=ev_hit,
            must_include_hit=include_hit,
            must_not_include_hit=exclude_hit,
            notes_used=notes_hit,
            context_mode_correct=context_mode_correct,
            actual_context_mode=actual_context_mode,
            error=error,
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
        return result

    async def run(self) -> tuple[list[EvaluationResult], Any]:
        """
        跑完整个测试集。
        """
        cases = load_cases(self.cases_path)
        results: list[EvaluationResult] = []

        for case in cases:
            result = await self._run_one(case)
            results.append(result)

        summary = summarize(results)
        return results, summary

    async def run_and_report(self, json_report_path: str, md_report_path: str) -> None:
        """
        跑完并写报告。
        """
        results, summary = await self.run()
        write_json_report(json_report_path, summary, results)
        write_markdown_report(md_report_path, summary, results)
