from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_tools import call_mcp_tool
from services.run_trace_service import default_run_trace_service

from .metrics import summarize
from .types import EvaluationResult


@dataclass(slots=True)
class MCPEvaluationCase:
    id: str
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    expect_ok: bool = True
    expected_error_code: str = ""
    description: str = ""


def load_mcp_cases(path: str | Path) -> list[MCPEvaluationCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cases: list[MCPEvaluationCase] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        args = item.get("args") or {}
        cases.append(MCPEvaluationCase(
            id=str(item.get("id") or "").strip(),
            tool_name=str(item.get("tool_name") or "").strip(),
            args=dict(args) if isinstance(args, dict) else {},
            expect_ok=bool(item.get("expect_ok", True)),
            expected_error_code=str(item.get("expected_error_code") or ""),
            description=str(item.get("description") or ""),
        ))
    return cases


class MCPEvaluationRunner:
    def __init__(self, cases_path: str, trace_service: Any = None):
        self.cases_path = cases_path
        self.trace_service = trace_service or default_run_trace_service

    def _summarize_trace_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        steps = payload.get("steps") or []
        if not isinstance(steps, list):
            steps = []

        failed_steps: list[dict[str, Any]] = []
        mcp_tool_steps: list[str] = []
        tool_error_codes: list[str] = []
        total_latency_ms = 0

        for step in steps:
            if not isinstance(step, dict):
                continue
            latency = step.get("latency_ms")
            if isinstance(latency, (int, float)):
                total_latency_ms += latency
            step_type = str(step.get("step_type") or "")
            step_name = str(step.get("step_name") or "")
            if step_type == "mcp_tool" or step_name.startswith("mcp:"):
                mcp_tool_steps.append(step_name)
            if str(step.get("status") or "").lower() == "failed":
                failed_steps.append({
                    "step_name": step_name,
                    "step_type": step_type,
                    "error": step.get("error") or "",
                })
            for code in self._extract_error_codes(step):
                if code not in tool_error_codes:
                    tool_error_codes.append(code)

        return {
            "trace_status": str(payload.get("status") or ""),
            "step_count": len(steps),
            "failed_steps": failed_steps,
            "mcp_tool_steps": mcp_tool_steps,
            "tool_steps": mcp_tool_steps,
            "total_latency_ms": round(total_latency_ms, 2),
            "token_usage": 0,
            "tool_error_codes": tool_error_codes,
        }

    def _load_trace_summary(self, run_id: str) -> tuple[dict[str, Any], str]:
        if not run_id:
            return {}, ""
        try:
            payload = self.trace_service.load_run(run_id)
            return self._summarize_trace_payload(payload), ""
        except Exception as exc:
            return {}, str(exc)

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

    async def _run_one(self, case: MCPEvaluationCase) -> EvaluationResult:
        start = time.perf_counter()
        error = ""
        payload: dict[str, Any]
        try:
            payload = call_mcp_tool(case.tool_name, case.args, trace_service=self.trace_service)
        except Exception as exc:
            error = str(exc)
            payload = {
                "ok": False,
                "data": None,
                "error": error,
                "error_code": "MCP_EVALUATION_ERROR",
                "summary": "",
                "trace": {},
            }

        latency_ms = (time.perf_counter() - start) * 1000.0
        trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
        run_id = str(trace.get("run_id") or "")
        trace_path = str(trace.get("trace_path") or "")
        trace_summary, trace_load_error = self._load_trace_summary(run_id)

        actual_ok = bool(payload.get("ok"))
        actual_error_code = str(payload.get("error_code") or "")
        ok_matches = actual_ok == case.expect_ok
        error_code_matches = actual_error_code == case.expected_error_code
        trace_hit = bool(run_id and trace_summary.get("mcp_tool_steps"))
        passed = ok_matches and error_code_matches and trace_hit and not error
        failure_reason = ""
        if not ok_matches:
            failure_reason = f"expected ok={case.expect_ok}, got ok={actual_ok}"
        elif not error_code_matches:
            failure_reason = f"expected error_code={case.expected_error_code}, got error_code={actual_error_code}"
        elif not trace_hit:
            failure_reason = "MCP trace run or mcp_tool step missing"
        elif error:
            failure_reason = error

        result = EvaluationResult(
            case_id=case.id,
            question=case.description or case.tool_name,
            mode="mcp",
            expected_route="mcp",
            actual_route="mcp",
            expected_tools=[case.tool_name],
            actual_tools=[case.tool_name] if case.tool_name else [],
            answer_text=json.dumps(payload, ensure_ascii=False, default=str),
            latency_ms=round(latency_ms, 2),
            token_usage=0,
            route_correct=True,
            tool_correct=bool(case.tool_name),
            tool_args_correct=True,
            keyword_hit=ok_matches,
            evidence_hit=trace_hit,
            must_include_hit=error_code_matches,
            must_not_include_hit=True,
            notes_used=True,
            context_mode_correct=True,
            actual_context_mode="mcp",
            error=error or str(payload.get("error") or ""),
            score=1.0 if passed else 0.0,
            run_id=run_id,
            trace_path=trace_path,
            failure_category="" if passed else "mcp_error",
            failure_reason=failure_reason,
            trace_summary=trace_summary,
            meta={
                "mcp_tool_name": case.tool_name,
                "arguments": case.args,
                "expected_ok": case.expect_ok,
                "actual_ok": actual_ok,
                "expected_error_code": case.expected_error_code,
                "actual_error_code": actual_error_code,
                "trace_load_error": trace_load_error,
                "payload_summary": payload.get("summary", ""),
            },
        )
        return result

    async def run(self):
        cases = load_mcp_cases(self.cases_path)
        results = []
        for case in cases:
            results.append(await self._run_one(case))
        return results, summarize(results)

