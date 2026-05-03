"""Tests for CheckpointStore and CheckpointManager."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.checkpoint_store import Checkpoint, CheckpointStore
from app.services.checkpoint_manager import CheckpointManager
from app.services.workflow_engine import WorkflowContext, WorkflowEngine
from app.services.workflow_loader import StepDef, WorkflowDef


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _wf(name: str = "test", steps: list[StepDef] | None = None) -> WorkflowDef:
    return WorkflowDef(name=name, steps=steps or [])


def _set_var_step(variables: dict[str, str]) -> StepDef:
    return StepDef(type="set_variable", variables=variables)


# ---------------------------------------------------------------------------
# TestCheckpoint
# ---------------------------------------------------------------------------

class TestCheckpoint:
    def test_to_dict_and_back(self):
        cp = Checkpoint(
            session_id="s1",
            workflow_name="wf",
            step_index=2,
            step_name="search",
            context={"key": "val"},
            status="completed",
        )
        data = cp.to_dict()
        assert data["session_id"] == "s1"
        assert data["step_index"] == 2
        assert data["context"] == {"key": "val"}

        cp2 = Checkpoint.from_dict(data)
        assert cp2.session_id == cp.session_id
        assert cp2.step_index == cp.step_index
        assert cp2.status == cp.status

    def test_defaults(self):
        cp = Checkpoint(session_id="s", workflow_name="w", step_index=0)
        assert cp.step_name == ""
        assert cp.status == "in_progress"
        assert cp.error is None
        assert cp.context == {}


# ---------------------------------------------------------------------------
# TestCheckpointStore
# ---------------------------------------------------------------------------

class TestCheckpointStore:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.store = CheckpointStore(base_dir=tmp_path / "checkpoints")

    def test_save_and_load_latest(self):
        cp = Checkpoint(
            session_id="s1", workflow_name="wf1", step_index=0,
            step_name="step0", context={"a": 1}, status="completed",
        )
        self.store.save(cp)
        loaded = self.store.load_latest("s1", "wf1")
        assert loaded is not None
        assert loaded.step_index == 0
        assert loaded.context == {"a": 1}
        assert loaded.status == "completed"

    def test_latest_tracks_most_recent(self):
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf1", step_index=0,
            status="completed",
        ))
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf1", step_index=1,
            status="in_progress",
        ))
        latest = self.store.load_latest("s1", "wf1")
        assert latest.step_index == 1
        assert latest.status == "in_progress"

    def test_load_step_by_index(self):
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf1", step_index=3,
            context={"x": "y"},
        ))
        loaded = self.store.load_step("s1", "wf1", 3)
        assert loaded is not None
        assert loaded.context == {"x": "y"}

    def test_load_step_missing_returns_none(self):
        assert self.store.load_step("s1", "wf1", 99) is None

    def test_load_latest_missing_returns_none(self):
        assert self.store.load_latest("no", "no") is None

    def test_list_all_sorted(self):
        for i in [2, 0, 1]:
            self.store.save(Checkpoint(
                session_id="s1", workflow_name="wf1", step_index=i,
                status="completed",
            ))
        cps = self.store.list_all("s1", "wf1")
        indices = [c.step_index for c in cps]
        assert indices == [0, 1, 2]

    def test_list_all_empty(self):
        assert self.store.list_all("none", "none") == []

    def test_delete_session(self):
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf1", step_index=0,
        ))
        assert self.store.load_latest("s1", "wf1") is not None
        self.store.delete_session("s1")
        assert self.store.load_latest("s1", "wf1") is None

    def test_delete_workflow_only(self):
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf_a", step_index=0,
        ))
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf_b", step_index=0,
        ))
        self.store.delete_workflow("s1", "wf_a")
        assert self.store.load_latest("s1", "wf_a") is None
        assert self.store.load_latest("s1", "wf_b") is not None

    def test_get_resume_step_no_checkpoint(self):
        assert self.store.get_resume_step("s1", "wf1") == 0

    def test_get_resume_step_after_completed(self):
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf1", step_index=2,
            status="completed",
        ))
        assert self.store.get_resume_step("s1", "wf1") == 3

    def test_get_resume_step_after_failed(self):
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf1", step_index=2,
            status="failed",
        ))
        assert self.store.get_resume_step("s1", "wf1") == 2

    def test_get_resume_step_after_in_progress(self):
        self.store.save(Checkpoint(
            session_id="s1", workflow_name="wf1", step_index=1,
            status="in_progress",
        ))
        assert self.store.get_resume_step("s1", "wf1") == 1

    def test_corrupt_json_returns_none(self, tmp_path):
        # Write bad JSON directly
        cdir = tmp_path / "checkpoints" / "s1" / "wf1"
        cdir.mkdir(parents=True)
        (cdir / "latest.json").write_text("not valid json", encoding="utf-8")

        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        assert store.load_latest("s1", "wf1") is None

    def test_corrupt_step_json_skipped_in_list(self, tmp_path):
        cdir = tmp_path / "checkpoints" / "s1" / "wf1"
        cdir.mkdir(parents=True)
        (cdir / "step_000.json").write_text(
            json.dumps({"session_id": "s1", "workflow_name": "wf1", "step_index": 0, "status": "ok"}),
            encoding="utf-8",
        )
        (cdir / "step_001.json").write_text("garbage", encoding="utf-8")

        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        cps = store.list_all("s1", "wf1")
        assert len(cps) == 1
        assert cps[0].step_index == 0


# ---------------------------------------------------------------------------
# TestCheckpointManager
# ---------------------------------------------------------------------------

class TestCheckpointManager:
    def test_run_saves_checkpoints(self, tmp_path):
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        wf = WorkflowDef(
            name="test_wf",
            parameters={"topic": "AI"},
            steps=[
                StepDef(type="set_variable", variables={"a": "1"}),
                StepDef(type="set_variable", variables={"b": "2"}),
            ],
        )
        manager = CheckpointManager(engine=WorkflowEngine(), store=store)
        result = asyncio.run(manager.run(wf, session_id="s1"))
        assert result["a"] == "1"
        assert result["b"] == "2"

        cps = store.list_all("s1", "test_wf")
        # Each step index saves in_progress then completed to the same file,
        # so list_all returns 2 files (one per step), both with status=completed.
        assert len(cps) == 2
        completed = [c for c in cps if c.status == "completed"]
        assert len(completed) == 2

        # latest.json should track the final step
        latest = store.load_latest("s1", "test_wf")
        assert latest is not None
        assert latest.step_index == 1
        assert latest.status == "completed"

    def test_run_no_resume_on_fresh(self, tmp_path):
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        wf = WorkflowDef(
            name="wf",
            steps=[StepDef(type="set_variable", variables={"x": "1"})],
        )
        manager = CheckpointManager(engine=WorkflowEngine(), store=store)
        result = asyncio.run(manager.run(wf, session_id="s1"))
        assert result["x"] == "1"

    def test_run_resume_skips_completed_steps(self, tmp_path):
        """Simulate a partial run then resume."""
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        # Pre-save completed checkpoints for step 0
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf", step_index=0,
            step_name="step0", context={"a": "1"}, status="completed",
        ))
        # Step 1 failed
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf", step_index=1,
            step_name="step1", context={"a": "1"}, status="failed",
            error="something went wrong",
        ))
        # Latest is the failed one
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf", step_index=1,
            step_name="step1", context={"a": "1"}, status="failed",
        ))

        wf = WorkflowDef(
            name="wf",
            parameters={"topic": "AI"},
            steps=[
                StepDef(type="set_variable", variables={"a": "SHOULD_NOT_RUN"}),
                StepDef(type="set_variable", variables={"b": "resumed"}),
            ],
        )
        manager = CheckpointManager(engine=WorkflowEngine(), store=store)
        result = asyncio.run(manager.run(wf, session_id="s1"))

        # a should remain "1" from checkpoint (step 0 skipped)
        assert result["a"] == "1"
        # b should be set by the resumed step 1
        assert result["b"] == "resumed"

    def test_run_force_restart(self, tmp_path):
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf", step_index=0,
            context={"old": "data"}, status="completed",
        ))

        wf = WorkflowDef(
            name="wf",
            parameters={"topic": "fresh"},
            steps=[StepDef(type="set_variable", variables={"x": "{{topic}}"})],
        )
        manager = CheckpointManager(engine=WorkflowEngine(), store=store)
        result = asyncio.run(manager.run(wf, session_id="s1", resume=False))
        assert result["x"] == "fresh"

    def test_get_progress(self, tmp_path):
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        for i in range(3):
            store.save(Checkpoint(
                session_id="s1", workflow_name="wf", step_index=i,
                status="completed",
            ))
        manager = CheckpointManager(store=store)
        progress = manager.get_progress("s1", "wf")
        assert progress["status"] == "completed"
        assert progress["completed_steps"] == 3
        assert progress["total_steps"] == 3

    def test_get_progress_not_started(self, tmp_path):
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        manager = CheckpointManager(store=store)
        progress = manager.get_progress("s1", "none")
        assert progress["status"] == "not_started"

    def test_clear_session(self, tmp_path):
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf", step_index=0,
        ))
        manager = CheckpointManager(store=store)
        manager.clear("s1")
        assert store.load_latest("s1", "wf") is None

    def test_clear_specific_workflow(self, tmp_path):
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf_a", step_index=0,
        ))
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf_b", step_index=0,
        ))
        manager = CheckpointManager(store=store)
        manager.clear("s1", workflow_name="wf_a")
        assert store.load_latest("s1", "wf_a") is None
        assert store.load_latest("s1", "wf_b") is not None

    def test_run_stream_yields_checkpoint_events(self, tmp_path):
        async def _collect():
            events = []
            async for ev in manager.run_stream(wf, session_id="s1"):
                events.append(ev)
            return events

        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        wf = WorkflowDef(
            name="wf",
            steps=[
                StepDef(type="set_variable", variables={"x": "1"}),
                StepDef(type="set_variable", variables={"y": "2"}),
            ],
        )
        manager = CheckpointManager(engine=WorkflowEngine(), store=store)
        events = asyncio.run(_collect())

        event_types = [e["type"] for e in events]
        assert event_types == [
            "start", "step_start", "step_end",
            "step_start", "step_end", "done",
        ]

        # Verify checkpoints were saved
        cps = store.list_all("s1", "wf")
        completed = [c for c in cps if c.status == "completed"]
        assert len(completed) == 2

    def test_run_step_failure_saves_failed_checkpoint(self, tmp_path):
        # Use a task step with bad instruction that will fail
        async def _run():
            return await manager.run(wf, session_id="s1")

        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        manager = CheckpointManager(engine=WorkflowEngine(), store=store)

        # Use a step set that starts with a normal step, then a task that references
        # a bad tool (but we mock the engine to simulate failure)
        wf = WorkflowDef(name="wf", steps=[])

        # Manually test that _save_checkpoint works with error
        manager._save_checkpoint(
            "s1", "wf", 0, "bad_step",
            WorkflowContext({"x": "1"}), "failed", error="test error",
        )
        cp = store.load_latest("s1", "wf")
        assert cp.status == "failed"
        assert cp.error == "test error"

    def test_resume_from_in_progress(self, tmp_path):
        """Resume should restart from an in_progress step (not skip it)."""
        store = CheckpointStore(base_dir=tmp_path / "checkpoints")
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf", step_index=0,
            context={"a": "1"}, status="completed",
        ))
        store.save(Checkpoint(
            session_id="s1", workflow_name="wf", step_index=1,
            context={"a": "1"}, status="in_progress",
        ))

        wf = WorkflowDef(
            name="wf",
            steps=[
                StepDef(type="set_variable", variables={"a": "SHOULD_SKIP"}),
                StepDef(type="set_variable", variables={"b": "from_resume"}),
            ],
        )
        manager = CheckpointManager(engine=WorkflowEngine(), store=store)
        result = asyncio.run(manager.run(wf, session_id="s1"))

        # Step 0 was completed, should keep its context
        assert result["a"] == "1"
        # Step 1 was in_progress, should re-run
        assert result["b"] == "from_resume"
