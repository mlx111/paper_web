from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


_SENSITIVE_KEYS = ("api_key", "apikey", "token", "password", "secret", "authorization")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_session_id(session_id: str) -> str:
    safe = (session_id or "default").strip() or "default"
    return safe.replace("/", "_").replace("\\", "_").replace(":", "_")


def sanitize_trace_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(sensitive in key_text.lower() for sensitive in _SENSITIVE_KEYS):
                sanitized[key_text] = "***"
            else:
                sanitized[key_text] = sanitize_trace_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_trace_payload(item) for item in value]
    return value


@dataclass(slots=True)
class RunTraceRun:
    run_id: str
    session_id: str
    trace_path: Path


class RunTraceStep:
    def __init__(self, service: "RunTraceService", run_id: str, payload: dict[str, Any]):
        self._service = service
        self._run_id = run_id
        self._payload = payload
        self._started_perf = time.perf_counter()

    @property
    def step_id(self) -> str:
        return self._payload["step_id"]

    def set_input(self, value: Any) -> None:
        self._payload["input"] = sanitize_trace_payload(value)
        self._service._persist_run(self._run_id)

    def set_output(self, value: Any) -> None:
        self._payload["output"] = sanitize_trace_payload(value)
        self._service._persist_run(self._run_id)

    def mark_failed(self, error: str) -> None:
        self._payload["status"] = "failed"
        self._payload["error"] = error
        self._service._persist_run(self._run_id)

    def __enter__(self) -> "RunTraceStep":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._payload["ended_at"] = _utc_now()
        self._payload["latency_ms"] = int((time.perf_counter() - self._started_perf) * 1000)
        if exc is None:
            if self._payload.get("status") != "failed":
                self._payload["status"] = "completed"
        else:
            self._payload["status"] = "failed"
            self._payload["error"] = str(exc)
        self._service._persist_run(self._run_id)
        return False


class RunTraceService:
    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[1] / "data" / "run_traces"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, dict[str, Any]] = {}
        self._paths: dict[str, Path] = {}

    def start_run(
        self,
        session_id: str,
        route: str,
        question: str,
        metadata: dict[str, Any] | None = None,
    ) -> RunTraceRun:
        run_id = uuid4().hex
        trace_path = self.base_dir / _safe_session_id(session_id) / f"{run_id}.json"
        payload = {
            "run_id": run_id,
            "session_id": session_id,
            "route": route,
            "question": question,
            "status": "running",
            "started_at": _utc_now(),
            "ended_at": None,
            "metadata": metadata or {},
            "error": None,
            "steps": [],
        }
        self._runs[run_id] = payload
        self._paths[run_id] = trace_path
        self._persist_run(run_id)
        return RunTraceRun(run_id=run_id, session_id=session_id, trace_path=trace_path)

    def step(
        self,
        run_id: str,
        step_name: str,
        step_type: str,
        parent_step_id: str | None = None,
    ) -> RunTraceStep:
        run = self._ensure_loaded(run_id)
        payload = {
            "step_id": uuid4().hex,
            "step_name": step_name,
            "step_type": step_type,
            "parent_step_id": parent_step_id,
            "status": "running",
            "started_at": _utc_now(),
            "ended_at": None,
            "latency_ms": None,
            "input": None,
            "output": None,
            "error": None,
        }
        run["steps"].append(payload)
        self._persist_run(run_id)
        return RunTraceStep(self, run_id, payload)

    def end_run(self, run_id: str, status: str = "completed", error: str | None = None) -> None:
        run = self._ensure_loaded(run_id)
        run["status"] = status
        run["ended_at"] = _utc_now()
        run["error"] = error
        run["summary"] = self._build_summary(run)
        self._persist_run(run_id)

    def load_run(self, run_id: str) -> dict[str, Any]:
        run = self._ensure_loaded(run_id)
        return json.loads(json.dumps(run, ensure_ascii=False, default=str))

    def summarize_run(self, run_id: str) -> dict[str, Any]:
        run = self._ensure_loaded(run_id)
        summary = self._build_summary(run)
        run["summary"] = summary
        self._persist_run(run_id)
        return json.loads(json.dumps(summary, ensure_ascii=False, default=str))

    def build_replay(self, run_id: str) -> dict[str, Any]:
        run = self._ensure_loaded(run_id)
        summary = self._build_summary(run)
        run["summary"] = summary
        self._persist_run(run_id)
        replay = {
            "run_id": run.get("run_id"),
            "session_id": run.get("session_id"),
            "route": run.get("route"),
            "question": run.get("question"),
            "status": run.get("status"),
            "summary": summary,
            "steps": run.get("steps") if isinstance(run.get("steps"), list) else [],
        }
        return json.loads(json.dumps(replay, ensure_ascii=False, default=str))

    def list_runs(self, session_id: str | None = None) -> list[dict[str, Any]]:
        paths = self._iter_trace_paths(session_id)
        runs = []
        for path in paths:
            try:
                runs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(runs, key=lambda item: item.get("started_at") or "", reverse=True)

    def get_trace_path(self, run_id: str) -> Path:
        self._ensure_loaded(run_id)
        return self._paths[run_id]

    def _ensure_loaded(self, run_id: str) -> dict[str, Any]:
        if run_id in self._runs:
            return self._runs[run_id]

        path = self._find_trace_path(run_id)
        if path is None:
            raise KeyError(f"Run trace not found: {run_id}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        self._runs[run_id] = payload
        self._paths[run_id] = path
        return payload

    def _persist_run(self, run_id: str) -> None:
        run = self._runs[run_id]
        path = self._paths[run_id]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(run, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _find_trace_path(self, run_id: str) -> Path | None:
        cached = self._paths.get(run_id)
        if cached and cached.exists():
            return cached

        for path in self.base_dir.glob(f"*{run_id}.json"):
            return path
        for path in self.base_dir.glob(f"*/{run_id}.json"):
            return path
        return None

    def _iter_trace_paths(self, session_id: str | None = None) -> list[Path]:
        if session_id is not None:
            return list((self.base_dir / _safe_session_id(session_id)).glob("*.json"))
        return list(self.base_dir.glob("*.json")) + list(self.base_dir.glob("*/*.json"))

    @staticmethod
    def _build_summary(run: dict[str, Any]) -> dict[str, Any]:
        steps = run.get("steps") if isinstance(run.get("steps"), list) else []
        failed_steps: list[str] = []
        tool_steps: list[str] = []
        mcp_tool_steps: list[str] = []
        tool_error_codes: list[str] = []
        total_latency_ms = 0

        for step in steps:
            if not isinstance(step, dict):
                continue
            step_name = str(step.get("step_name") or "")
            step_type = str(step.get("step_type") or "")
            if isinstance(step.get("latency_ms"), int):
                total_latency_ms += step["latency_ms"]
            if step.get("status") == "failed":
                failed_steps.append(step_name)
            if step_type in {"tool", "mcp_tool"} or step_name.startswith(("tool:", "mcp:")):
                tool_steps.append(step_name)
            if step_type == "mcp_tool" or step_name.startswith("mcp:"):
                mcp_tool_steps.append(step_name)

            output = step.get("output")
            if isinstance(output, dict):
                error_code = output.get("error_code")
                if error_code:
                    tool_error_codes.append(str(error_code))

        return {
            "trace_status": run.get("status", "unknown"),
            "step_count": len(steps),
            "failed_steps": failed_steps,
            "tool_steps": tool_steps,
            "mcp_tool_steps": mcp_tool_steps,
            "tool_error_codes": tool_error_codes,
            "total_latency_ms": total_latency_ms,
            "error": run.get("error"),
        }


default_run_trace_service = RunTraceService()
