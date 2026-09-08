from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

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

