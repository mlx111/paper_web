"""JSON-file checkpoint persistence for workflow execution recovery.

Checkpoints are stored as:
    {base_dir}/{session_id}/{workflow_name}/step_{index:03d}.json
    {base_dir}/{session_id}/{workflow_name}/latest.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Checkpoint:
    """A single checkpoint snapshot."""

    __slots__ = (
        "session_id", "workflow_name", "step_index", "step_name",
        "context", "status", "error", "timestamp",
    )

    def __init__(
        self,
        session_id: str,
        workflow_name: str,
        step_index: int,
        step_name: str = "",
        context: dict[str, Any] | None = None,
        status: str = "in_progress",
        error: str | None = None,
        timestamp: str | None = None,
    ):
        self.session_id = session_id
        self.workflow_name = workflow_name
        self.step_index = step_index
        self.step_name = step_name
        self.context = dict(context or {})
        self.status = status
        self.error = error
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workflow_name": self.workflow_name,
            "step_index": self.step_index,
            "step_name": self.step_name,
            "context": self.context,
            "status": self.status,
            "error": self.error,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            session_id=str(data.get("session_id", "")),
            workflow_name=str(data.get("workflow_name", "")),
            step_index=int(data.get("step_index", 0)),
            step_name=str(data.get("step_name", "")),
            context=dict(data.get("context", {}) or {}),
            status=str(data.get("status", "in_progress")),
            error=data.get("error"),
            timestamp=str(data.get("timestamp", "")),
        )


class CheckpointStore:
    """Save, load, list, and delete workflow checkpoints as JSON files."""

    def __init__(self, base_dir: str | Path = ""):
        if not base_dir:
            base_dir = Path(__file__).resolve().parent.parent / "data" / "checkpoints"
        self.base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # path helpers
    # ------------------------------------------------------------------

    def _checkpoint_dir(self, session_id: str, workflow_name: str) -> Path:
        return self.base_dir / session_id / workflow_name

    def _step_path(self, session_id: str, workflow_name: str, step_index: int) -> Path:
        return self._checkpoint_dir(session_id, workflow_name) / f"step_{step_index:03d}.json"

    def _latest_path(self, session_id: str, workflow_name: str) -> Path:
        return self._checkpoint_dir(session_id, workflow_name) / "latest.json"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save(self, cp: Checkpoint) -> Path:
        cdir = self._checkpoint_dir(cp.session_id, cp.workflow_name)
        cdir.mkdir(parents=True, exist_ok=True)

        data = cp.to_dict()
        payload = json.dumps(data, ensure_ascii=False, indent=2)

        step_path = self._step_path(cp.session_id, cp.workflow_name, cp.step_index)
        step_path.write_text(payload, encoding="utf-8")

        latest_path = self._latest_path(cp.session_id, cp.workflow_name)
        latest_path.write_text(payload, encoding="utf-8")

        return step_path

    def load_latest(self, session_id: str, workflow_name: str) -> Checkpoint | None:
        path = self._latest_path(session_id, workflow_name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Checkpoint.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def load_step(self, session_id: str, workflow_name: str, step_index: int) -> Checkpoint | None:
        path = self._step_path(session_id, workflow_name, step_index)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Checkpoint.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def list_all(self, session_id: str, workflow_name: str) -> list[Checkpoint]:
        cdir = self._checkpoint_dir(session_id, workflow_name)
        if not cdir.exists():
            return []

        checkpoints: list[Checkpoint] = []
        for path in sorted(cdir.glob("step_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                checkpoints.append(Checkpoint.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                pass
        return checkpoints

    def delete_session(self, session_id: str) -> None:
        import shutil
        session_dir = self.base_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)

    def delete_workflow(self, session_id: str, workflow_name: str) -> None:
        import shutil
        cdir = self._checkpoint_dir(session_id, workflow_name)
        if cdir.exists():
            shutil.rmtree(cdir)

    def get_resume_step(self, session_id: str, workflow_name: str) -> int:
        """Return the step index to resume from.

        If the latest checkpoint was completed, return its index + 1.
        If the latest checkpoint was in_progress or failed, return its index.
        If no checkpoint exists, return 0.
        """
        latest = self.load_latest(session_id, workflow_name)
        if latest is None:
            return 0
        if latest.status == "completed":
            return latest.step_index + 1
        return latest.step_index
