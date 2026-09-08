"""一键运行 evaluation，输出报告和汇总指标."""
import asyncio
import sys
from pathlib import Path

# 切换到 app 目录运行，让 from agents.xxx 等导入正常工作
_app_dir = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(_app_dir))

import json

from evaluation.runner import EvaluationRunner


async def main():
    cases_path = _app_dir / "evaluation" / "cases.json"
    report_dir = _app_dir / "evaluation" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / "report.json"
    md_path = report_dir / "report.md"

    runner = EvaluationRunner(str(cases_path))
    await runner.run_and_report(str(json_path), str(md_path))

    # 读取报告并打印摘要
    report = json.loads(json_path.read_text(encoding="utf-8"))
    summary = report["summary"]

    print("=" * 50)
    print("Evaluation Results")
    print("=" * 50)
    print(f"  Total Cases:    {summary['total_cases']}")
    print(f"  Passed Cases:   {summary['passed_cases']}")
    print(f"  Route Accuracy: {summary['route_accuracy']:.2%}")
    print(f"  Tool Accuracy:  {summary['tool_accuracy']:.2%}")
    print(f"  Keyword Hit:    {summary['keyword_hit_rate']:.2%}")
    print(f"  Evidence Hit:   {summary['evidence_hit_rate']:.2%}")
    print(f"  Avg Latency:    {summary['avg_latency_ms']:.1f} ms")
    print(f"  Avg Score:      {summary['avg_score']:.2f}")
    print("=" * 50)

    # token_usage 从单条结果统计
    all_tokens = [r.get("token_usage", 0) for r in report["results"]]
    if all_tokens:
        print(f"  Avg Token Usage: {sum(all_tokens)/len(all_tokens):.0f}")
        print(f"  Total Tokens:    {sum(all_tokens)}")

    failed = report.get("failed_cases", [])
    if failed:
        print(f"\nFailed Cases ({len(failed)}):")
        for f in failed:
            print(f"  - {f['case_id']}: score={f['score']}  error={f['error']}")
    else:
        print("\nAll cases passed!")

    print(f"\nFull report: {json_path}")
    print(f"Markdown:    {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
