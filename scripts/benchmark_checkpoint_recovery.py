"""
Benchmark script for CheckpointManager recovery.

Simulates multi-step workflow interruptions by pre-seeding checkpoints
(which is exactly how real failures look after restart), then tests recovery.

Detection strategy: seed checkpoints with DIFFERENT variable values than
what the workflow would set. If a step is correctly skipped, the seeded
value remains. If it's incorrectly re-executed, the workflow value overwrites it.

Metrics:
  - Total simulated interruptions
  - Successful recovery count (+ rate)
  - Step-skipping correctness (completed steps not re-executed)
  - Average recovery time
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

_app_dir = str(Path(__file__).parent.parent / "app")
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
_root_dir = str(Path(__file__).parent.parent)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)

from services.checkpoint_store import Checkpoint, CheckpointStore
from services.checkpoint_manager import CheckpointManager
from services.workflow_engine import WorkflowEngine
from services.workflow_loader import StepDef, WorkflowDef


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_step(name: str, var_key: str, var_val: str) -> StepDef:
    return StepDef(
        name=name,
        type="set_variable",
        variables={var_key: var_val},
    )


def build_workflow(step_count: int = 10) -> WorkflowDef:
    steps = [
        _make_step(f"step_{i}", f"var_{i}", f"value_{i}")
        for i in range(step_count)
    ]
    return WorkflowDef(
        name=f"bench_wf_{step_count}steps",
        parameters={"initial": "seed"},
        steps=steps,
    )


# Sentinel prefix used in seeded checkpoints to detect re-execution.
# If the final result has this prefix, the step was SKIPPED (correct).
# If it has the normal "value_{i}", the step was RE-EXECUTED.
_CHECKPOINT_PREFIX = "CP_"


def seed_checkpoints(
    store: CheckpointStore,
    session_id: str,
    workflow_name: str,
    completed_up_to: int,
    total_steps: int,
) -> int:
    """Pre-save checkpoints simulating a crash after `completed_up_to` steps.

    Steps [0, completed_up_to) get completed checkpoints with values
    prefixed with CP_ so we can detect re-execution.
    Step completed_up_to gets a failed checkpoint.

    Returns the seeded step count (= completed_up_to).
    """
    ctx: dict[str, str] = {}
    for j in range(total_steps):
        ctx[f"var_{j}"] = f"{_CHECKPOINT_PREFIX}value_{j}"

    for i in range(completed_up_to):
        store.save(Checkpoint(
            session_id=session_id,
            workflow_name=workflow_name,
            step_index=i,
            step_name=f"step_{i}",
            context=dict(ctx),
            status="completed",
        ))

    if completed_up_to < total_steps:
        store.save(Checkpoint(
            session_id=session_id,
            workflow_name=workflow_name,
            step_index=completed_up_to,
            step_name=f"step_{completed_up_to}",
            context=dict(ctx),
            status="failed",
            error="Simulated interruption",
        ))

    return completed_up_to


async def run_recovery_scenario(
    tmp_dir: Path,
    scenario_name: str,
    step_count: int,
    completed_up_to: int,
) -> dict:
    """Test recovery from a partial run checkpointed up to completed_up_to."""
    store = CheckpointStore(base_dir=tmp_dir / scenario_name)
    wf = build_workflow(step_count)
    session_id = f"session_{scenario_name}"

    seed_checkpoints(store, session_id, wf.name, completed_up_to, step_count)

    manager = CheckpointManager(engine=WorkflowEngine(), store=store)
    t0 = time.perf_counter()
    result = await manager.run(wf, session_id=session_id, resume=True)
    recovery_time_ms = (time.perf_counter() - t0) * 1000.0

    # Detect which steps were skipped vs re-executed
    skipped = 0
    re_executed = 0
    violations = []  # incorrect re-execution where step should have been skipped

    for i in range(step_count):
        actual = result.get(f"var_{i}", "")

        if i < completed_up_to:
            # Should be from checkpoint (CP_ prefix)
            if actual == f"{_CHECKPOINT_PREFIX}value_{i}":
                skipped += 1
            elif actual == f"value_{i}":
                re_executed += 1
                violations.append(i)
            else:
                violations.append(i)
        else:
            # Should be freshly executed
            if actual == f"value_{i}":
                pass  # correct
            elif actual == "":
                violations.append(i)

    all_skipped_correctly = len(violations) == 0

    return {
        "scenario": scenario_name,
        "step_count": step_count,
        "interrupted_after": completed_up_to,
        "remaining_steps": step_count - completed_up_to,
        "recovery_success": all_skipped_correctly,
        "skipped_count": skipped,
        "re_executed_count": re_executed,
        "violations": violations,
        "recovery_time_ms": round(recovery_time_ms, 2),
    }


async def run_stress_test(
    tmp_dir: Path,
    scenario_name: str,
    step_count: int = 10,
    iterations: int = 20,
) -> dict:
    """Stress test: recover at every possible interrupt point, repeatedly."""
    store = CheckpointStore(base_dir=tmp_dir / scenario_name)
    wf = build_workflow(step_count)
    session_id = f"stress_{scenario_name}"

    total_time_ms = 0.0
    all_ok = True
    violations = []

    for i in range(iterations):
        interrupt_at = i % step_count
        store.delete_session(session_id)

        seed_checkpoints(store, session_id, wf.name, interrupt_at, step_count)

        manager = CheckpointManager(engine=WorkflowEngine(), store=store)
        t0 = time.perf_counter()
        result = await manager.run(wf, session_id=session_id, resume=True)
        elapsed = (time.perf_counter() - t0) * 1000.0
        total_time_ms += elapsed

        for s in range(step_count):
            actual = result.get(f"var_{s}", "")
            if s < interrupt_at:
                if actual != f"{_CHECKPOINT_PREFIX}value_{s}":
                    all_ok = False
                    violations.append((i, interrupt_at, s, actual))
            elif s >= interrupt_at:
                if actual != f"value_{s}":
                    all_ok = False
                    violations.append((i, interrupt_at, s, actual))

    return {
        "scenario": f"{scenario_name}_stress",
        "iterations": iterations,
        "step_count": step_count,
        "all_ok": all_ok,
        "violation_count": len(violations),
        "violations": violations,
        "total_recovery_time_ms": round(total_time_ms, 2),
        "avg_recovery_time_ms": round(total_time_ms / iterations, 2),
    }


async def main():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ckpt_bench_") as tmp:
        tmp_dir = Path(tmp)
        results: list[dict] = []

        print("=" * 72)
        print("  Checkpoint 恢复基准测试")
        print("=" * 72)

        scenarios = [
            ("A_early",     "步骤 1/10 处中断", 10, 1),
            ("B_mid",       "步骤 5/10 处中断", 10, 5),
            ("C_late",      "步骤 9/10 处中断", 10, 9),
            ("D_all_done",  "全部完成后再恢复", 10, 10),
            ("E_none_done", "一步都没跑就恢复", 10, 0),
        ]

        for name, desc, step_count, completed in scenarios:
            print(f"\n[{name}] {desc}")
            r = await run_recovery_scenario(tmp_dir, name, step_count, completed)
            results.append(r)
            print(f"  {'✓' if r['recovery_success'] else '✗'}  "
                  f"recovery={r['recovery_time_ms']:.1f}ms, "
                  f"skipped={r['skipped_count']}, "
                  f"re_exec={r['re_executed_count']}, "
                  f"remaining={r['remaining_steps']}")

        print("\n[F_large]  50 步，第 25 步中断")
        r = await run_recovery_scenario(tmp_dir, "F_large", 50, 25)
        results.append(r)
        print(f"  {'✓' if r['recovery_success'] else '✗'}  "
              f"recovery={r['recovery_time_ms']:.1f}ms, "
              f"skipped={r['skipped_count']}, fresh={r['remaining_steps']}")

        print("\n[G_stress]  压力测试 — 遍历所有中断点 x 20 次")
        stress = await run_stress_test(tmp_dir, "G_stress", step_count=10, iterations=20)
        results.append(stress)
        print(f"  {'✓' if stress['all_ok'] else '✗'}  "
              f"avg={stress['avg_recovery_time_ms']:.2f}ms, "
              f"violations={stress['violation_count']}")

        print(f"\n{'=' * 72}")
        print("  汇总")
        print(f"{'=' * 72}")
        print(f"  {'Scenario':<22} {'Steps':<6} {'Interrupted':<12} {'Skipped':<8} {'Re-execed':<9} {'Time':<8}")
        for r in results:
            if "interrupted_after" in r:
                print(f"  {r['scenario']:<22} {r['step_count']:<6} "
                      f"{'after '+str(r['interrupted_after']):<12} "
                      f"{r['skipped_count']:<8} {r['re_executed_count']:<9} "
                      f"{r['recovery_time_ms']:<8.0f}")
            else:
                print(f"  {r['scenario']:<22} {r['step_count']:<6} "
                      f"{'stress':<12} {'':8} {'':9} "
                      f"avg={r['avg_recovery_time_ms']:.1f}ms")

        recoverable = [r for r in results if "interrupted_after" in r]
        successes = sum(1 for r in recoverable if r["recovery_success"])
        total_skipped = sum(r["skipped_count"] for r in recoverable)
        total_re_exec = sum(r["re_executed_count"] for r in recoverable)
        avg_time = sum(r["recovery_time_ms"] for r in recoverable) / len(recoverable)

        print(f"\n  关键恢复指标:")
        print(f"    恢复成功率:          {successes}/{len(recoverable)} ({100*successes//len(recoverable)}%)")
        print(f"    步骤跳过正确率:      {total_re_exec == 0} (跳过 {total_skipped} 步, 重执行 {total_re_exec} 步)")
        print(f"    平均恢复耗时:        {avg_time:.2f} ms")
        print(f"    压力测试平均耗时:    {stress['avg_recovery_time_ms']:.2f} ms ({stress['iterations']} 次)")
        print(f"{'=' * 72}")


if __name__ == "__main__":
    asyncio.run(main())
