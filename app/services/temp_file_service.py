"""Session-scoped temporary file storage for ad-hoc document parsing."""

from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

try:
    from settings.config import config
except Exception:  # pragma: no cover - allows isolated unit tests
    config = None


def _ok(**payload: Any) -> dict[str, Any]:
    return {"ok": True, **payload}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


class TempFileService:
    allowed_extensions = {".txt", ".text", ".md", ".markdown", ".pdf", ".docx", ".html", ".htm"}

    def __init__(
        self,
        root_dir: Path | None = None,
        max_files_per_session: int | None = None,
        max_file_size_bytes: int | None = None,
        max_total_size_bytes: int | None = None,
        ttl_seconds: int | None = None,
    ):
        project_root = Path(__file__).resolve().parents[2]
        self.root_dir = Path(root_dir or (project_root / "app" / "data" / "tmp")).resolve()
        self.max_files_per_session = int(
            max_files_per_session
            if max_files_per_session is not None
            else getattr(config, "temp_file_max_count", 5)
        )
        max_size_mb = getattr(config, "temp_file_max_size_mb", 20)
        max_total_mb = getattr(config, "temp_file_max_total_size_mb", 50)
        self.max_file_size_bytes = int(
            max_file_size_bytes if max_file_size_bytes is not None else max_size_mb * 1024 * 1024
        )
        self.max_total_size_bytes = int(
            max_total_size_bytes
            if max_total_size_bytes is not None
            else max_total_mb * 1024 * 1024
        )
        self.ttl_seconds = int(
            ttl_seconds if ttl_seconds is not None else getattr(config, "temp_file_ttl_seconds", 7200)
        )

    def save_temp_file(self, session_id: str, filename: str, content: bytes) -> dict[str, Any]:
        session_id = self._sanitize_session_id(session_id)
        if not session_id:
            return _err("INVALID_SESSION", "session_id must be a non-empty string")
        if not filename:
            return _err("INVALID_FILENAME", "filename must be a non-empty string")
        if content is None:
            return _err("INVALID_CONTENT", "content cannot be None")

        self.cleanup_expired_files()

        safe_filename = self._sanitize_filename(filename)
        suffix = Path(safe_filename).suffix.lower()
        if suffix not in self.allowed_extensions:
            return _err("UNSUPPORTED_FILE_TYPE", f"unsupported temp file type: {suffix}")

        size = len(content)
        if size > self.max_file_size_bytes:
            return _err("TEMP_FILE_TOO_LARGE", "temporary file exceeds single-file size limit")

        current_files = self.list_temp_files(session_id)
        if len(current_files) >= self.max_files_per_session:
            return _err("TEMP_FILE_LIMIT_EXCEEDED", "temporary file count limit exceeded")

        current_total = sum(int(item.get("size", 0)) for item in current_files)
        if current_total + size > self.max_total_size_bytes:
            return _err("TEMP_TOTAL_SIZE_EXCEEDED", "temporary files exceed session total size limit")

        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        file_id = uuid.uuid4().hex[:8]
        stored_name = f"{file_id}_{safe_filename}"
        path = session_dir / stored_name
        path.write_bytes(content)

        return _ok(
            file_id=file_id,
            filename=safe_filename,
            stored_name=stored_name,
            file_path=str(path),
            size=size,
            session_id=session_id,
        )

    def list_temp_files(self, session_id: str) -> list[dict[str, Any]]:
        session_id = self._sanitize_session_id(session_id)
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return []

        files: list[dict[str, Any]] = []
        for path in sorted(session_dir.iterdir(), key=lambda item: item.stat().st_mtime):
            if not path.is_file():
                continue
            stored_name = path.name
            file_id, filename = self._split_stored_name(stored_name)
            stat = path.stat()
            files.append(
                {
                    "file_id": file_id,
                    "filename": filename,
                    "stored_name": stored_name,
                    "file_path": str(path),
                    "size": stat.st_size,
                    "created_at": stat.st_mtime,
                    "session_id": session_id,
                }
            )
        return files

    def clear_session_temp_files(self, session_id: str) -> bool:
        session_id = self._sanitize_session_id(session_id)
        session_dir = self._session_dir(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir)
        return True

    def cleanup_expired_files(self) -> int:
        if self.ttl_seconds <= 0 or not self.root_dir.exists():
            return 0

        now = time.time()
        removed = 0
        for session_dir in self.root_dir.iterdir():
            if not session_dir.is_dir():
                continue
            for path in list(session_dir.iterdir()):
                if not path.is_file():
                    continue
                if now - path.stat().st_mtime > self.ttl_seconds:
                    path.unlink(missing_ok=True)
                    removed += 1
            try:
                if not any(session_dir.iterdir()):
                    session_dir.rmdir()
            except OSError:
                pass
        return removed

    def build_context_text(self, session_id: str) -> str:
        files = self.list_temp_files(session_id)
        if not files:
            return ""
        lines = [
            "Current session temporary files. Call extract_document_text when the user asks about them."
        ]
        for item in files:
            lines.append(f"- {item['filename']}: {item['file_path']}")
        return "\n".join(lines)

    def _session_dir(self, session_id: str) -> Path:
        return self.root_dir / self._sanitize_session_id(session_id)

    @staticmethod
    def _sanitize_session_id(session_id: str) -> str:
        session_id = str(session_id or "").strip()
        return re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        name = Path(filename).name.strip()
        name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", name)
        return name[:180] or "upload.tmp"

    @staticmethod
    def _split_stored_name(stored_name: str) -> tuple[str, str]:
        if "_" not in stored_name:
            return "", stored_name
        file_id, filename = stored_name.split("_", 1)
        return file_id, filename


temp_file_service = TempFileService()
