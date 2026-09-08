"""Export mypaperweb evaluation cases to the LLMOps platform's agent_trajectory dataset.

Converts ``app/evaluation/cases.json`` into the LLMOps case schema (each case's
``expected_tools`` / ``expected_tool_args`` become the expected trajectory
steps), then either writes a JSON file or pushes it to a running LLMOps instance
via its REST API.

Usage:
    python scripts/export_llmops_dataset.py                       # write JSON file only
    python scripts/export_llmops_dataset.py --push                # push to LLMOps (localhost:8000)
    python scripts/export_llmops_dataset.py --push --llmops-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
CASES_PATH = APP_DIR / "evaluation" / "cases.json"
OUT_PATH = APP_DIR / "evaluation" / "llmops_trajectory_cases.json"

DATASET_NAME = "mypaperweb-agent-trajectory"


def convert_case(case: dict) -> dict:
    """Convert one mypaperweb evaluation case to an LLMOps agent_trajectory case."""
    tools = case.get("expected_tools") or []
    args_map = case.get("expected_tool_args") or {}

    steps: list[dict] = []
    for tool in tools:
        tool_args = args_map.get(tool, {}) if isinstance(args_map, dict) else {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        steps.append({"type": "tool_call", "tool_name": tool, "tool_args": tool_args})

    keywords = case.get("must_include") or case.get("expected_keywords") or []
    steps.append({"type": "final", "content": " ".join(keywords) or "answer"})

    # reference_answer holds the expected trajectory as a JSON string.
    expected_trajectory = {"steps": steps, "success": True}

    tags = [t for t in [case.get("mode"), case.get("expected_route"), case.get("id")] if t]
    return {
        "case_type": "agent_trajectory",
        "input": case.get("question", ""),
        "reference_answer": json.dumps(expected_trajectory, ensure_ascii=False),
        "tags": tags,
        "difficulty": case.get("difficulty"),
        "extra_metadata": {
            "source_case_id": case.get("id"),
            "mode": case.get("mode"),
            "description": case.get("description", ""),
            "expected_keywords": case.get("expected_keywords", []),
        },
    }


def load_cases() -> list[dict]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return [c for c in data if c.get("question")]


def push_to_llmops(llmops_url: str, cases: list[dict]) -> None:
    import requests

    base = llmops_url.rstrip("/")

    ds_resp = requests.get(f"{base}/api/datasets", timeout=15)
    ds_resp.raise_for_status()
    existing = [d for d in ds_resp.json().get("items", []) if d.get("name") == DATASET_NAME]

    if existing:
        dataset_id = existing[0]["id"]
        print(f"reuse existing dataset id={dataset_id}")
    else:
        create = requests.post(
            f"{base}/api/datasets",
            json={
                "name": DATASET_NAME,
                "description": "mypaperweb agent trajectory cases (exported from cases.json)",
                "case_type": "agent_trajectory",
            },
            timeout=15,
        )
        create.raise_for_status()
        dataset_id = create.json()["id"]
        print(f"created dataset id={dataset_id}")

    imp = requests.post(
        f"{base}/api/datasets/{dataset_id}/import",
        json={"cases": cases},
        timeout=60,
    )
    imp.raise_for_status()
    print(f"imported {len(cases)} cases -> dataset {dataset_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="push to a running LLMOps instance")
    parser.add_argument("--llmops-url", default="http://localhost:8000", help="LLMOps backend base URL")
    args = parser.parse_args()

    raw_cases = load_cases()
    cases = [convert_case(c) for c in raw_cases]

    OUT_PATH.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(cases)} cases -> {OUT_PATH}")

    if args.push:
        push_to_llmops(args.llmops_url, cases)
    return 0


if __name__ == "__main__":
    sys.exit(main())
