import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger


class IndexManifestService:
    """Persist file index fingerprints to support incremental startup sync."""

    def __init__(self, manifest_path: Optional[Path] = None):
        project_root = Path(__file__).resolve().parent.parent
        self.manifest_path = manifest_path or (project_root / "data" / "index_manifest.json")
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("索引清单服务初始化完成: {}", self.manifest_path)

    def _default_manifest(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "updated_at": None,
            "files": {},
        }

    def _load(self) -> Dict[str, Any]:
        if not self.manifest_path.exists():
            return self._default_manifest()

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return self._default_manifest()
            data.setdefault("schema_version", 1)
            data.setdefault("updated_at", None)
            data.setdefault("files", {})
            if not isinstance(data["files"], dict):
                data["files"] = {}
            return data
        except Exception as exc:
            logger.warning("索引清单读取失败，使用空清单: {}", exc)
            return self._default_manifest()

    def _save(self, manifest: Dict[str, Any]) -> None:
        manifest["updated_at"] = datetime.now().isoformat()
        tmp_path = self.manifest_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        tmp_path.replace(self.manifest_path)

    def _normalize_key(self, file_path: str | Path) -> str:
        return Path(file_path).resolve().as_posix()

    def get_record(self, file_path: str | Path) -> Dict[str, Any] | None:
        manifest = self._load()
        return manifest.get("files", {}).get(self._normalize_key(file_path))

    def is_unchanged(self, file_path: str | Path, *, size: int, mtime_ns: int) -> bool:
        record = self.get_record(file_path)
        if not record:
            return False
        return record.get("size") == size and record.get("mtime_ns") == mtime_ns

    def mark_indexed(self, file_path: str | Path, *, size: int, mtime_ns: int) -> None:
        manifest = self._load()
        key = self._normalize_key(file_path)
        manifest.setdefault("files", {})[key] = {
            "size": size,
            "mtime_ns": mtime_ns,
            "indexed_at": datetime.now().isoformat(),
        }
        self._save(manifest)

    def remove_record(self, file_path: str | Path) -> bool:
        manifest = self._load()
        key = self._normalize_key(file_path)
        files = manifest.get("files", {})
        if key not in files:
            return False
        files.pop(key, None)
        self._save(manifest)
        return True

    def list_records(self) -> Dict[str, Any]:
        manifest = self._load()
        return manifest.get("files", {})


index_manifest_service = IndexManifestService()
