from __future__ import annotations

import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from evaluation.reporter import write_json_report, write_markdown_report


router = APIRouter(prefix="/evaluation", tags=["evaluation"])

APP_DIR = Path(__file__).resolve().parents[1]
CASES_PATH = APP_DIR / "evaluation" / "cases.json"
MCP_CASES_PATH = APP_DIR / "evaluation" / "mcp_cases.json"
REPORTS_DIR = APP_DIR / "evaluation" / "reports"
EvaluationRunner = None


def _ok(data: Any) -> dict[str, Any]:
    return {"code": 200, "message": "success", "data": data}


def _safe_report_path(report_name: str) -> Path:
    name = Path(report_name).name
    if name != report_name or not name.endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid report name")
    path = REPORTS_DIR / name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Evaluation report not found: {report_name}")
    return path


def _read_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {exc}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Evaluation report must be a JSON object")
    return payload


def _summary_to_dict(summary: Any) -> dict[str, Any]:
    if is_dataclass(summary):
        data = asdict(summary)
    elif isinstance(summary, dict):
        data = dict(summary)
    else:
        data = {
            key: getattr(summary, key)
            for key in (
                "total_cases",
                "passed_cases",
                "route_accuracy",
                "tool_accuracy",
                "tool_args_accuracy",
                "keyword_hit_rate",
                "evidence_hit_rate",
                "avg_latency_ms",
                "avg_score",
            )
            if hasattr(summary, key)
        }
    data.pop("failed_cases", None)
    return data


def _load_runner_class():
    global EvaluationRunner
    if EvaluationRunner is None:
        from evaluation.runner import EvaluationRunner as Runner

        EvaluationRunner = Runner
    return EvaluationRunner


@router.get("/reports")
async def list_evaluation_reports():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in sorted(REPORTS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _read_report(path)
        stat = path.stat()
        reports.append(
            {
                "name": path.name,
                "path": path.as_posix(),
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "size_bytes": stat.st_size,
                "summary": payload.get("summary") or {},
            }
        )
    return _ok({"count": len(reports), "reports": reports})


@router.get("/reports/{report_name}")
async def get_evaluation_report(report_name: str):
    path = _safe_report_path(report_name)
    payload = _read_report(path)
    return _ok(payload)


@router.post("/run")
async def run_evaluation():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORTS_DIR / f"report-{timestamp}.json"
    md_path = REPORTS_DIR / f"report-{timestamp}.md"

    runner_class = _load_runner_class()
    runner = runner_class(str(CASES_PATH))
    results, summary = await runner.run()
    write_json_report(json_path, summary, results)
    write_markdown_report(md_path, summary, results)

    return _ok(
        {
            "report_name": json_path.name,
            "markdown_name": md_path.name,
            "json_path": json_path.as_posix(),
            "md_path": md_path.as_posix(),
            "summary": _summary_to_dict(summary),
        }
    )

@router.post("/run/mcp")
async def run_mcp_evaluation():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORTS_DIR / f"mcp-report-{timestamp}.json"
    md_path = REPORTS_DIR / f"mcp-report-{timestamp}.md"

    from evaluation.mcp_runner import MCPEvaluationRunner

    runner = MCPEvaluationRunner(str(MCP_CASES_PATH))
    results, summary = await runner.run()
    write_json_report(json_path, summary, results)
    write_markdown_report(md_path, summary, results)

    return _ok(
        {
            "report_name": json_path.name,
            "markdown_name": md_path.name,
            "json_path": json_path.as_posix(),
            "md_path": md_path.as_posix(),
            "summary": _summary_to_dict(summary),
        }
    )


# ---------- Standard evaluation target endpoint (for external LLMOps platforms) ----------

class TargetEvaluationRequest(BaseModel):
    query: str
    case_type: str | None = None
    mode: str | None = None  # "quick" | "deep"; inferred from case_type when omitted
    tools: list[str] | None = None
    context_ids: list[str] | None = None
    # Multi-turn driving: an external LLMOps platform reuses one session_id
    # across turns so the agent's conversation history is exercised.
    session_id: str | None = None
    # Multi-turn turns must bypass the semantic cache (see EvaluationRunner).
    bypass_cache: bool = False


@router.post("/target")
async def evaluation_target(body: TargetEvaluationRequest):
    """Standard single-query endpoint driven by an external LLMOps platform.

    Runs the chosen agent on ``query`` and returns a flat JSON payload with the
    final answer and the tool-call trajectory, aligned to the platform's
    agent_trajectory schema::

        {"answer": str, "success": bool, "session_id": str,
         "steps": [{"type": "tool_call", "tool_name": ..., "tool_args": {...}},
                   {"type": "final", "content": ...}],
         "tool_called": str|None, "tool_args": dict|None}
    """
    mode = (body.mode or "").strip().lower()
    if mode not in ("quick", "deep", "multi", "harness"):
        # Plain QA routes to the lightweight quick agent; anything needing
        # retrieval / tools uses the deep research agent.
        mode = "quick" if (body.case_type or "").strip().lower() == "qa" else "deep"

    runner_class = _load_runner_class()
    runner = runner_class(str(CASES_PATH))
    # Reuse the caller-supplied session (multi-turn evaluation); otherwise
    # mint a fresh one so single-turn calls stay stateless.
    session_id = (body.session_id or "").strip() or f"llmops-{uuid.uuid4().hex[:12]}"
    result = await runner.invoke_agent(
        body.query, mode=mode, session_id=session_id, skip_cache=body.bypass_cache
    )

    tool_calls = result.get("tool_calls") or []
    steps: list[dict[str, Any]] = [
        {
            "type": "tool_call",
            "tool_name": str(tc.get("name")),
            "tool_args": tc.get("args") if isinstance(tc.get("args"), dict) else {},
        }
        for tc in tool_calls
        if tc.get("name")
    ]

    answer = result.get("answer") or ""
    error = result.get("error") or ""
    steps.append({"type": "final", "content": answer})

    meta = result.get("meta") or {}
    token_usage = result.get("token_usage") or {}
    if not token_usage:
        # 兜底：trace 提取失败时按字符估算（与内部口径一致：len//2）
        token_usage = {
            "prompt_tokens": max(0, len(body.query) // 2),
            "completion_tokens": max(0, len(answer) // 2),
            "total_tokens": max(0, (len(body.query) + len(answer)) // 2),
            "estimated": True,
            "source": "char_estimate",
        }

    payload: dict[str, Any] = {
        "answer": answer,
        "success": bool(answer) and not error,
        "session_id": session_id,
        "steps": steps,
        "mode": mode,
        "run_id": str(meta.get("run_id") or ""),
        "model": str(meta.get("model") or ""),
        "routed": bool(meta.get("routed")),
        "route_tier": meta.get("route_tier"),
        "cache_hit": bool(meta.get("cache_hit")),
        "token_usage": {
            "prompt_tokens": int(token_usage.get("prompt_tokens") or 0),
            "completion_tokens": int(token_usage.get("completion_tokens") or 0),
            "total_tokens": int(token_usage.get("total_tokens") or 0),
            "estimated": bool(token_usage.get("estimated", False)),
            "source": str(token_usage.get("source") or ""),
        },
        # Flat aliases kept for tool_calling / single-tool metric compatibility.
        "tool_called": (result.get("tool_names") or [None])[0] if result.get("tool_names") else None,
        "tool_args": tool_calls[0].get("args") if tool_calls and isinstance(tool_calls[0].get("args"), dict) else None,
    }
    if error:
        payload["error"] = error[:500]
    return payload

