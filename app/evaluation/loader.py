from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import EvaluationCase


def load_cases(path: str | Path) -> list[EvaluationCase]:
    """
    从 JSON 文件加载评估样本。

    期望格式是一个 list，每个元素是一条 case。
    """
    case_path = Path(path)
    raw = json.loads(case_path.read_text(encoding="utf-8"))

    cases: list[EvaluationCase] = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        known_keys = {
            "id",
            "question",
            "mode",
            "expected_route",
            "expected_tools",
            "expected_tool_args",
            "expected_keywords",
            "expected_evidence",
            "expected_answer_type",
            "difficulty",
        }
        extra = {k: v for k, v in item.items() if k not in known_keys}

        expected_tool_args_raw = item.get("expected_tool_args", {}) or {}
        expected_tool_args: dict[str, dict[str, str]] = {}
        for tool_name, args in expected_tool_args_raw.items():
            if isinstance(args, dict):
                expected_tool_args[str(tool_name)] = {str(k): str(v) for k, v in args.items()}

        cases.append(
            EvaluationCase(
                id=str(item.get("id", "")).strip(),
                question=str(item.get("question", "")).strip(),
                mode=str(item.get("mode", "deep")).strip(),
                expected_route=str(item.get("expected_route", "deep")).strip(),
                expected_tools=list(item.get("expected_tools", []) or []),
                expected_tool_args=expected_tool_args,
                expected_keywords=list(item.get("expected_keywords", []) or []),
                expected_evidence=list(item.get("expected_evidence", []) or []),
                expected_answer_type=str(item.get("expected_answer_type", "analysis")).strip(),
                difficulty=str(item.get("difficulty", "medium")).strip(),
                extra=extra,
            )
        )

    return cases
