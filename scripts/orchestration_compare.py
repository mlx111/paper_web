"""Build a single-vs-multi-agent orchestration comparison on the LLMOps platform.

同一批「研究型复杂任务」分别在两种编排下评测：

* mode=deep  —— 单智能体（DeepAgentService），期望轨迹含联网检索工具 ``web_search``；
* mode=multi —— 多智能体（MultiAgentService，supervisor + searcher/analyzer/citation），
  子 agent 在隔离上下文中执行、其内部工具不冒泡到主管轨迹，因此主管轨迹的关键
  动作是 ``task`` handoff（分派给子 agent），期望轨迹含 ``task``。

两种模式各自对照「自己应做的关键动作」来打分：
  - TaskSuccess          是否成功产出答案；
  - ToolSelectionAccuracy deep=是否主动联网检索；multi=是否触发 task 分派；
  - StepEfficiency/latency 编排开销（multi 因 handoff + 子 agent 多轮而更高）。

Usage:
    python scripts/orchestration_compare.py --push --runs
    python scripts/orchestration_compare.py --push            # 仅建/导入数据集
    python scripts/orchestration_compare.py --status          # 查询最近对比 run 结果
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _request(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    """Minimal JSON HTTP helper using the stdlib (no `requests` dependency)."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} -> {exc.code}: {detail[:300]}") from exc

LLMOPS_URL = "http://localhost:8000"
TARGET_URL = "http://host.docker.internal:8080/evaluation/target"
TARGET_TIMEOUT = 180
CONCURRENCY = 2

DATASET_DEEP = "mypaperweb-research-deep"
DATASET_MULTI = "mypaperweb-research-multi"
RUN_DEEP = "orch-compare-deep"
RUN_MULTI = "orch-compare-multi"

# 研究型复杂任务：均需要联网检索 + 综合分析，适合体现多智能体分工。
RESEARCH_CASES: list[dict] = [
    {
        "id": "rs_001",
        "question": "我在做 Agent 方向的求职作品集，请联网检索最新资料，调研 LLM 多智能体系统中 supervisor / orchestrator 编排模式的典型架构，以及 LangGraph、CrewAI、AutoGen 等代表框架的分工方式，最后给出要点总结。",
    },
    {
        "id": "rs_002",
        "question": "请联网检索并调研 2024-2025 年 Agentic RAG 的主流高级技术方案（例如 corrective RAG、self-RAG、adaptive RAG、agentic retrieval），说明它们相对朴素 RAG 解决了什么问题。",
    },
    {
        "id": "rs_003",
        "question": "请联网检索最新资料，调研大模型智能体（LLM agent）的权威评测基准，例如 AgentBench、tau-bench、GAIA、SWE-bench，说明它们各自评测什么维度、有何难点。",
    },
    {
        "id": "rs_004",
        "question": "我在实现 MCP Host，请联网检索 Model Context Protocol（MCP）协议的设计目标、传输方式（stdio / streamable-http）以及当前工具生态现状，给出一份技术调研小结。",
    },
    {
        "id": "rs_005",
        "question": "请联网检索「上下文工程 Context Engineering」相对传统 prompt engineering 的新方法与工程实践（如上下文压缩、记忆管理、工具结果组织），总结可落地的最佳实践。",
    },
]


def build_cases(mode: str) -> list[dict]:
    """Convert research tasks to LLMOps cases for the given agent mode.

    deep 期望主管直接调用 web_search；multi 期望主管通过 task handoff 分派子 agent。
    """
    expected_tool = "web_search" if mode == "deep" else "task"
    cases: list[dict] = []
    for item in RESEARCH_CASES:
        # expected trajectory：一次关键工具动作 + 最终答复
        expected_trajectory = {
            "steps": [
                {"type": "tool_call", "tool_name": expected_tool, "tool_args": {}},
                {"type": "final", "content": "answer"},
            ],
            "success": True,
        }
        cases.append(
            {
                "case_type": "agent_trajectory",
                "input": item["question"],
                "reference_answer": json.dumps(expected_trajectory, ensure_ascii=False),
                "tags": [mode, "orchestration-compare", item["id"]],
                "difficulty": "hard",
                "extra_metadata": {
                    "source_case_id": item["id"],
                    "mode": mode,
                    "orchestration": "single" if mode == "deep" else "multi",
                    "description": f"research task for {mode} orchestration",
                },
            }
        )
    return cases


def _get_or_create_dataset(base: str, name: str) -> int:
    resp = _request("GET", f"{base}/api/datasets", timeout=15)
    existing = [d for d in resp.get("items", []) if d.get("name") == name]
    if existing:
        print(f"reuse dataset {name} id={existing[0]['id']}")
        return existing[0]["id"]
    created = _request(
        "POST",
        f"{base}/api/datasets",
        {
            "name": name,
            "description": f"research tasks for orchestration comparison ({name.split('-')[-1]})",
            "case_type": "agent_trajectory",
        },
        timeout=15,
    )
    dataset_id = created["id"]
    print(f"created dataset {name} id={dataset_id}")
    return dataset_id


def push_datasets(base: str) -> dict[str, int]:
    ids: dict[str, int] = {}
    for mode, ds_name in (("deep", DATASET_DEEP), ("multi", DATASET_MULTI)):
        dataset_id = _get_or_create_dataset(base, ds_name)
        cases = build_cases(mode)
        _request("POST", f"{base}/api/datasets/{dataset_id}/import", {"cases": cases}, timeout=60)
        print(f"  imported {len(cases)} cases (mode={mode}) -> dataset {dataset_id}")
        ids[mode] = dataset_id
    return ids


def create_run(base: str, name: str, dataset_id: int) -> int:
    # 避免重名：先查已有同名 run
    runs = _request("GET", f"{base}/api/runs", timeout=15).get("items", [])
    for run in runs:
        if run.get("name") == name:
            print(f"reuse run {name} id={run['id']} status={run.get('status')}")
            return run["id"]
    payload = {
        "name": name,
        "dataset_id": dataset_id,
        "concurrency": CONCURRENCY,
        "target_url": TARGET_URL,
        "target_type": "http",
        "target_timeout": TARGET_TIMEOUT,
    }
    created = _request("POST", f"{base}/api/runs", payload, timeout=30)
    run_id = created.get("id")
    print(f"created run {name} id={run_id} (dataset {dataset_id}, timeout={TARGET_TIMEOUT}s, concurrency={CONCURRENCY})")
    return run_id


def show_status(base: str) -> None:
    runs = _request("GET", f"{base}/api/runs", timeout=15).get("items", [])
    want = {RUN_DEEP: "single(deep)", RUN_MULTI: "multi"}
    for run in sorted(runs, key=lambda r: r.get("id", 0), reverse=True):
        if run.get("name") not in want:
            continue
        label = want[run["name"]]
        print(
            f"[{label:12s}] run={run['id']} status={run['status']} "
            f"total={run['total_cases']} passed={run['passed_cases']} "
            f"avg_score={run['avg_score']} avg_latency_ms={round(run['avg_latency_ms'] or 0, 1)}"
        )
        # 逐 case 指标
        try:
            detail = _request("GET", f"{base}/api/runs/{run['id']}/results", timeout=30)
        except RuntimeError:
            continue
        for r in detail.get("items", []):
            scores = r.get("scores") or {}
            traj = scores.get("agent_trajectory") or scores
            ts = (traj.get("TaskSuccess") or {}).get("score")
            tsel = (traj.get("ToolSelectionAccuracy") or {}).get("score")
            eff = (traj.get("StepEfficiency") or {}).get("score")
            print(
                f"    case={r.get('case_id')} status={r.get('status')} "
                f"TaskSuccess={ts} ToolSel={tsel} StepEff={eff} latency={r.get('latency_ms')}ms"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llmops-url", default=LLMOPS_URL)
    parser.add_argument("--push", action="store_true", help="create/import datasets")
    parser.add_argument("--runs", action="store_true", help="also create evaluation runs")
    parser.add_argument("--status", action="store_true", help="show latest comparison run results")
    args = parser.parse_args()

    base = args.llmops_url.rstrip("/")

    if args.status:
        show_status(base)
        return 0

    if not args.push:
        # 默认仅写出 cases 到本地文件，便于检查
        out = Path(__file__).resolve().parents[1] / "app" / "evaluation" / "orchestration_compare_cases.json"
        out.write_text(
            json.dumps({"deep": build_cases("deep"), "multi": build_cases("multi")}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"wrote cases -> {out} (use --push to import, --runs to start runs)")
        return 0

    ids = push_datasets(base)
    if args.runs:
        create_run(base, RUN_DEEP, ids["deep"])
        create_run(base, RUN_MULTI, ids["multi"])
        print("\n两个 run 已启动（multi 真实 LLM 较慢，约需 5-10 分钟）。稍后用 --status 查看结果。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
