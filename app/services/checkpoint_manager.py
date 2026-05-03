"""Checkpoint-aware workflow execution with resume and retry support.

Wraps WorkflowEngine to automatically persist context state at each step,
enabling recovery from failures without re-running completed steps.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from services.checkpoint_store import Checkpoint, CheckpointStore
from services.workflow_engine import WorkflowContext, WorkflowEngine
from services.workflow_loader import WorkflowDef


class CheckpointManager:
    """Checkpoint-aware wrapper around WorkflowEngine.

    Usage:
        manager = CheckpointManager(engine, store)
        result = await manager.run(wf, session_id="abc", params={"q": "..."})

        # On failure, call again with the same session_id to resume:
        result = await manager.run(wf, session_id="abc", params={"q": "..."})
    """

    def __init__(
        self,
        engine: WorkflowEngine | None = None,
        store: CheckpointStore | None = None,
    ):
        self.engine = engine or WorkflowEngine()
        self.store = store or CheckpointStore()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def run(
        self,
        wf: WorkflowDef,
        session_id: str,
        params: dict[str, Any] | None = None,
        resume: bool = True,
    ) -> dict[str, Any]:
        """Execute a workflow with checkpointing. Set resume=False to force restart."""
        if resume:
            start_idx = self.store.get_resume_step(session_id, wf.name)
            if start_idx > 0:
                latest = self.store.load_latest(session_id, wf.name)
                if latest and latest.context:
                    ctx = WorkflowContext(dict(latest.context))
                    return await self._run_from(wf, session_id, ctx, start_idx)

        ctx = WorkflowContext({**wf.parameters, **(params or {})})
        return await self._run_from(wf, session_id, ctx, 0)

    async def run_stream(
        self,
        wf: WorkflowDef,
        session_id: str,
        params: dict[str, Any] | None = None,
        resume: bool = True,
    ):
        """Streaming workflow execution with checkpointing."""
        if resume:
            start_idx = self.store.get_resume_step(session_id, wf.name)
            if start_idx > 0:
                latest = self.store.load_latest(session_id, wf.name)
                if latest and latest.context:
                    ctx = WorkflowContext(dict(latest.context))
                else:
                    ctx = WorkflowContext({**wf.parameters, **(params or {})})
                    start_idx = 0
            else:
                ctx = WorkflowContext({**wf.parameters, **(params or {})})
        else:
            ctx = WorkflowContext({**wf.parameters, **(params or {})})
            start_idx = 0

        yield {"type": "start", "workflow": wf.name, "session_id": session_id}

        for idx in range(start_idx, len(wf.steps)):
            step = wf.steps[idx]
            yield {"type": "step_start", "step": step.name or step.type, "index": idx}

            self._save_checkpoint(
                session_id, wf.name, idx, step.name or step.type,
                ctx, "in_progress",
            )

            try:
                await self.engine._dispatch_step(step, ctx, None, wf.config.max_tool_rounds)
                self._save_checkpoint(
                    session_id, wf.name, idx, step.name or step.type,
                    ctx, "completed",
                )
                yield {"type": "step_end", "step": step.name or step.type, "index": idx}
            except Exception as exc:
                self._save_checkpoint(
                    session_id, wf.name, idx, step.name or step.type,
                    ctx, "failed", str(exc),
                )
                yield {"type": "step_error", "step": step.name or step.type, "error": str(exc)}
                logger.error("Step {} failed at index {}: {}", step.name, idx, exc)
                break

        yield {"type": "done", "output": ctx.as_dict()}

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    async def _run_from(
        self,
        wf: WorkflowDef,
        session_id: str,
        ctx: WorkflowContext,
        start_idx: int,
    ) -> dict[str, Any]:
        for idx in range(start_idx, len(wf.steps)):
            step = wf.steps[idx]
            self._save_checkpoint(
                session_id, wf.name, idx, step.name or step.type,
                ctx, "in_progress",
            )

            try:
                await self.engine._dispatch_step(step, ctx, None, wf.config.max_tool_rounds)
                self._save_checkpoint(
                    session_id, wf.name, idx, step.name or step.type,
                    ctx, "completed",
                )
            except Exception as exc:
                self._save_checkpoint(
                    session_id, wf.name, idx, step.name or step.type,
                    ctx, "failed", str(exc),
                )
                raise

        return ctx.as_dict()

    def _save_checkpoint(
        self,
        session_id: str,
        workflow_name: str,
        step_index: int,
        step_name: str,
        ctx: WorkflowContext,
        status: str,
        error: str | None = None,
    ) -> None:
        try:
            cp = Checkpoint(
                session_id=session_id,
                workflow_name=workflow_name,
                step_index=step_index,
                step_name=step_name,
                context=ctx.as_dict(),
                status=status,
                error=error,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self.store.save(cp)
        except Exception:
            logger.warning("Failed to save checkpoint: step={}", step_index)

    # ------------------------------------------------------------------
    # status / history
    # ------------------------------------------------------------------

    def get_progress(self, session_id: str, workflow_name: str) -> dict[str, Any]:
        """Return a progress summary for a session's workflow."""
        checkpoints = self.store.list_all(session_id, workflow_name)
        if not checkpoints:
            return {"status": "not_started", "completed_steps": 0, "total_steps": 0}

        latest = self.store.load_latest(session_id, workflow_name)
        return {
            "status": latest.status if latest else "unknown",
            "completed_steps": sum(1 for c in checkpoints if c.status == "completed"),
            "failed_steps": sum(1 for c in checkpoints if c.status == "failed"),
            "total_steps": len(checkpoints),
            "latest_step": latest.step_index if latest else -1,
            "latest_step_name": latest.step_name if latest else "",
        }

    def clear(self, session_id: str, workflow_name: str = "") -> None:
        """Delete checkpoints for a session or a specific workflow."""
        if workflow_name:
            self.store.delete_workflow(session_id, workflow_name)
        else:
            self.store.delete_session(session_id)
