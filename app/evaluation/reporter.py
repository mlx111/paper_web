from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .types import EvaluationResult, EvaluationSummary


def _failure_category_counts(summary: EvaluationSummary) -> dict[str, int]:
    counts = Counter(item.failure_category or "uncategorized" for item in summary.failed_cases)
    return dict(sorted(counts.items()))


def write_json_report(output_path: str | Path, summary: EvaluationSummary, results: list[EvaluationResult]) -> None:
    """
    写 JSON 报告。

    适合后面做自动化对比和历史存档。
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "summary": {
            "total_cases": summary.total_cases,
            "passed_cases": summary.passed_cases,
            "route_accuracy": summary.route_accuracy,
            "tool_accuracy": summary.tool_accuracy,
            "tool_args_accuracy": summary.tool_args_accuracy,
            "keyword_hit_rate": summary.keyword_hit_rate,
            "evidence_hit_rate": summary.evidence_hit_rate,
            "avg_latency_ms": summary.avg_latency_ms,
            "avg_score": summary.avg_score,
            "failure_categories": _failure_category_counts(summary),
        },
        "results": [asdict(item) for item in results],
        "failed_cases": [asdict(item) for item in summary.failed_cases],
    }

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_report(output_path: str | Path, summary: EvaluationSummary, results: list[EvaluationResult]) -> None:
    """
    写 Markdown 报告。

    适合人读，方便你快速扫结果。
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# Evaluation Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Total Cases: {summary.total_cases}")
    lines.append(f"- Passed Cases: {summary.passed_cases}")
    lines.append(f"- Route Accuracy: {summary.route_accuracy}")
    lines.append(f"- Tool Accuracy: {summary.tool_accuracy}")
    lines.append(f"- Keyword Hit Rate: {summary.keyword_hit_rate}")
    lines.append(f"- Evidence Hit Rate: {summary.evidence_hit_rate}")
    lines.append(f"- Avg Latency(ms): {summary.avg_latency_ms}")
    lines.append(f"- Avg Score: {summary.avg_score}")
    lines.append("")
    lines.append("## Failure Categories")
    category_counts = _failure_category_counts(summary)
    if category_counts:
        for category, count in category_counts.items():
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- none: 0")
    lines.append("")
    lines.append("## Failed Cases")
    for item in summary.failed_cases:
        lines.append(
            f"- `{item.case_id}` | score={item.score} | category={item.failure_category or 'uncategorized'} "
            f"| reason={item.failure_reason} | route={item.actual_route} | tools={item.actual_tools} "
            f"| token_usage={item.token_usage} | run_id={item.run_id} | trace_path={item.trace_path} | error={item.error}"
        )

    path.write_text("\n".join(lines), encoding="utf-8")
