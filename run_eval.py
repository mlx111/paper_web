"""一键运行 evaluation，拿简历指标数据。"""
import asyncio
import json
import sys
from pathlib import Path

# 切换到 app 目录，让项目内部 import 正常工作
_app_dir = Path(__file__).parent / "app"
sys.path.insert(0, str(_app_dir))

from loguru import logger
from evaluation.runner import EvaluationRunner
from services.mlivus_client_service import mlivus_client_service
from services.vector_index_service import vector_index_service


async def main():
    # 1. 连接 Milvus 并索引 uploads 中的文件
    logger.info("正在连接 Milvus...")
    mlivus_client_service.connect()
    logger.info("Milvus 连接成功")

    logger.info("正在扫描 uploads 目录并索引...")
    index_result = vector_index_service.sync_directory_incrementally()
    logger.info(
        "索引完成: 总数={}, 成功={}, 失败={}",
        index_result.total_files,
        index_result.success_count,
        index_result.fail_count,
    )

    # 2. 运行评估
    cases_path = _app_dir / "evaluation" / "cases.json"
    output_dir = _app_dir / "evaluation" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "report.json"

    runner = EvaluationRunner(str(cases_path))
    results, summary = await runner.run()

    # 打印汇总
    print("\n" + "=" * 50)
    print("📊  Evaluation 结果")
    print("=" * 50)
    print(f"  总用例:     {summary.total_cases}")
    print(f"  通过:       {summary.passed_cases}")
    print(f"  Tool Acc:   {summary.tool_accuracy:.2%}")
    print(f"  Tool Args:  {summary.tool_args_accuracy:.2%}")
    print(f"  Keyword Hit:{summary.keyword_hit_rate:.2%}")
    print(f"  Evidence Hit:{summary.evidence_hit_rate:.2%}")
    print(f"  平均延迟:   {summary.avg_latency_ms:.1f} ms")
    print(f"  平均得分:   {summary.avg_score:.2f}")
    print("=" * 50)

    # token 统计
    tokens = [r.token_usage for r in results]
    if tokens:
        print(f"  平均 Token:  {sum(tokens)/len(tokens):.0f}")
        print(f"  总 Token:    {sum(tokens)}")
        print("=" * 50)

    # 失败的用例
    failed = [r for r in results if r.score < 0.75]
    if failed:
        print(f"\n❌ 失败 ({len(failed)}):")
        for f in failed:
            print(f"  - {f.case_id}: score={f.score}  {f.error}")
    else:
        print("\n✅ 全部通过!")

    # 保存 JSON 报告
    report = {
        "summary": {
            "total_cases": summary.total_cases,
            "passed_cases": summary.passed_cases,
            "tool_accuracy": summary.tool_accuracy,
            "keyword_hit_rate": summary.keyword_hit_rate,
            "evidence_hit_rate": summary.evidence_hit_rate,
            "avg_latency_ms": summary.avg_latency_ms,
            "avg_score": summary.avg_score,
        },
        "results": [
            {
                "case_id": r.case_id,
                "question": r.question,
                "latency_ms": r.latency_ms,
                "token_usage": r.token_usage,
                "score": r.score,
                "error": r.error,
            }
            for r in results
        ],
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📁 完整报告已保存: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
