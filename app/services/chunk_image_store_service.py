"""Local storage for document images referenced by RAG chunks."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any


IMAGE_PLACEHOLDER_RE = re.compile(r"<<IMAGE:[0-9a-f]{8}>>")


def extract_image_placeholders(text: str) -> list[str]:
    """Return unique image placeholders in first-seen order."""
    seen: set[str] = set()
    placeholders: list[str] = []
    for match in IMAGE_PLACEHOLDER_RE.findall(text or ""):
        if match not in seen:
            seen.add(match)
            placeholders.append(match)
    return placeholders


def strip_image_placeholders(text: str) -> str:
    """Remove image placeholders and collapse whitespace for embedding text."""
    cleaned = IMAGE_PLACEHOLDER_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


class ChunkImageStore:
    def __init__(
        self,
        image_root: str | Path,
        mapping_path: str | Path,
        public_url_prefix: str = "/file/image",
    ):
        self.image_root = Path(image_root)
        self.mapping_path = Path(mapping_path)
        self.public_url_prefix = public_url_prefix.rstrip("/")

    def save_image(
        self,
        image_bytes: bytes,
        ext: str,
        file_id: str,
        file_name: str,
        chunk_id: str,
        page_number: int | None = None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        image_id = uuid.uuid4().hex[:8]
        clean_ext = (ext or "png").lower().lstrip(".")
        if clean_ext == "jpeg":
            clean_ext = "jpg"

        file_dir = self.image_root / self._safe_segment(file_id or "default")
        file_dir.mkdir(parents=True, exist_ok=True)
        image_path = file_dir / f"{image_id}.{clean_ext}"
        image_path.write_bytes(image_bytes)

        placeholder = f"<<IMAGE:{image_id}>>"
        record = {
            "image_id": image_id,
            "placeholder": placeholder,
            "chunk_id": chunk_id,
            "file_id": file_id,
            "file_name": file_name,
            "image_path": image_path.as_posix(),
            "page_number": page_number,
            "sort_order": sort_order,
        }

        mapping = self._load_mapping()
        mapping[placeholder] = record
        self._save_mapping(mapping)
        return record

    def resolve_image_map(self, placeholders: list[str]) -> dict[str, str]:
        mapping = self._load_mapping()
        image_map: dict[str, str] = {}
        for placeholder in placeholders:
            record = mapping.get(placeholder)
            if not record:
                continue
            image_id = record.get("image_id")
            if image_id:
                image_map[placeholder] = f"{self.public_url_prefix}/{image_id}"
        return image_map

    def resolve_image_map_from_text(self, text: str) -> dict[str, str]:
        return self.resolve_image_map(extract_image_placeholders(text))

    def get_image_path(self, image_id: str) -> Path | None:
        mapping = self._load_mapping()
        for record in mapping.values():
            if record.get("image_id") == image_id:
                path = Path(record.get("image_path", ""))
                return path if path.exists() else None
        return None

    def _load_mapping(self) -> dict[str, Any]:
        if not self.mapping_path.exists():
            return {}
        try:
            return json.loads(self.mapping_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_mapping(self, mapping: dict[str, Any]) -> None:
        self.mapping_path.parent.mkdir(parents=True, exist_ok=True)
        self.mapping_path.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_segment(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "default"


default_chunk_image_store = ChunkImageStore(
    image_root=Path(__file__).resolve().parent.parent / "data" / "images",
    mapping_path=Path(__file__).resolve().parent.parent / "data" / "chunk_images.json",
    public_url_prefix="/file/image",
)
