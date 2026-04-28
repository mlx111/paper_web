"""Session-scoped storage for presentation user materials."""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any


class PresentationMaterialService:
    def __init__(self, storage_root: Path | None = None):
        project_root = Path(__file__).resolve().parents[2]
        self.storage_root = Path(storage_root or (project_root / "app" / "data" / "presentation_materials")).resolve()

    def save_material_entries(self, session_id: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        session_id = self._sanitize_session_id(session_id)
        if not session_id:
            raise ValueError("session_id must be a non-empty string")

        normalized_entries = [self._normalize_material_entry(session_id, entry) for entry in entries or []]
        current = self.load_materials(session_id).get("materials", [])
        materials = current + normalized_entries
        payload = {
            "session_id": session_id,
            "material_count": len(materials),
            "materials": materials,
            "saved_at": time.time(),
        }
        materials_path = self._materials_path(session_id)
        materials_path.parent.mkdir(parents=True, exist_ok=True)
        materials_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "session_id": session_id,
            "material_count": len(materials),
            "materials_path": str(materials_path),
            "materials": materials,
        }

    def save_uploaded_material(
        self,
        session_id: str,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        session_id = self._sanitize_session_id(session_id)
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        if not filename:
            raise ValueError("filename must be a non-empty string")
        if content is None:
            raise ValueError("content cannot be None")

        stored_name = self._build_stored_name(filename)
        upload_dir = self._uploads_dir(session_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / stored_name
        file_path.write_bytes(content)

        material_type = self._infer_material_type(filename, mime_type)
        entry = {
            "material_id": uuid.uuid4().hex,
            "source_type": "upload",
            "material_type": material_type,
            "title": Path(filename).name,
            "file_path": str(file_path),
            "mime_type": mime_type or "",
            "created_at": time.time(),
            "tags": [],
        }
        self.save_material_entries(session_id, [entry])
        return {
            "session_id": session_id,
            "file_path": str(file_path),
            "material_type": material_type,
            "material_id": entry["material_id"],
        }

    def load_materials(self, session_id: str) -> dict[str, Any]:
        session_id = self._sanitize_session_id(session_id)
        materials_path = self._materials_path(session_id)
        if not materials_path.exists():
            return {
                "session_id": session_id,
                "material_count": 0,
                "materials_path": str(materials_path),
                "materials": [],
            }
        try:
            payload = json.loads(materials_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        materials = payload.get("materials") or []
        return {
            "session_id": session_id,
            "material_count": len(materials),
            "materials_path": str(materials_path),
            "materials": materials,
        }

    def clear_session_materials(self, session_id: str) -> bool:
        session_id = self._sanitize_session_id(session_id)
        session_dir = self._session_dir(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir)
        return True

    def _normalize_material_entry(self, session_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        entry = dict(entry or {})
        normalized = {
            "material_id": str(entry.get("material_id") or uuid.uuid4().hex),
            "session_id": session_id,
            "source_type": str(entry.get("source_type") or entry.get("sourceType") or "paste"),
            "material_type": str(entry.get("material_type") or entry.get("materialType") or "text"),
            "title": self._clean_text(entry.get("title")),
            "content": self._clean_text(entry.get("content")),
            "url": self._clean_text(entry.get("url")),
            "file_path": self._clean_text(entry.get("file_path") or entry.get("filePath")),
            "mime_type": self._clean_text(entry.get("mime_type") or entry.get("mimeType")),
            "notes": self._clean_text(entry.get("notes")),
            "created_at": entry.get("created_at") or entry.get("createdAt") or time.time(),
            "tags": self._normalize_tags(entry.get("tags")),
            "metadata": entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {},
        }
        if not normalized["title"] and normalized["url"]:
            normalized["title"] = normalized["url"]
        return normalized

    def _materials_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "materials.json"

    def _uploads_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "uploads"

    def _session_dir(self, session_id: str) -> Path:
        return self.storage_root / self._sanitize_session_id(session_id)

    @staticmethod
    def _sanitize_session_id(session_id: str) -> str:
        session_id = str(session_id or "").strip()
        return re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _normalize_tags(tags: Any) -> list[str]:
        if not tags:
            return []
        if isinstance(tags, (list, tuple, set)):
            return [str(item).strip() for item in tags if str(item).strip()]
        text = str(tags).strip()
        return [text] if text else []

    @staticmethod
    def _build_stored_name(filename: str) -> str:
        safe_name = Path(filename).name.strip() or "upload.bin"
        safe_name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", safe_name)
        return f"{uuid.uuid4().hex[:8]}_{safe_name}"

    @staticmethod
    def _infer_material_type(filename: str, mime_type: str | None) -> str:
        suffix = Path(filename).suffix.lower()
        if mime_type and mime_type.startswith("image/"):
            return "image"
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}:
            return "image"
        return "document"


presentation_material_service = PresentationMaterialService()
