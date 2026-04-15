from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class NoteService:
    """
    结构化笔记服务。

    这个类不是聊天历史，而是长期记忆：
    - 用来记录关键结论
    - 用来记录任务状态
    - 用来记录待办、偏好、约束
    - 用来记录后续对话中值得反复引用的信息

    笔记会按 session_id 单独保存成 JSON 文件。
    """

    def __init__(self, session_id: str, storage_path: Path):
        self.session_id = str(session_id).strip()
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_path / f"{self.session_id}.json"

    def _now(self) -> str:
        """统一使用 UTC 时间，便于排查和排序。"""
        return datetime.now().isoformat()

    def _read_all(self) -> list[dict[str, Any]]:
        """
        读取当前会话的全部笔记。

        文件不存在时返回空列表。
        文件损坏时也返回空列表，避免直接把流程打断。
        """
        if not self.file_path.exists():
            return []

        try:
            raw = self.file_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            return []

        return []

    def _write_all(self, notes: list[dict[str, Any]]) -> None:
        """
        原子写回。

        先写临时文件，再替换正式文件，
        这样可以尽量避免中途写坏导致数据损坏。
        """
        tmp_path = self.file_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(notes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.file_path)

    def list_notes(self, limit: int | None = None) -> list[dict[str, Any]]:
        """
        列出当前会话的笔记。

        默认按更新时间倒序，最近写的优先返回。
        """
        notes = self._read_all()
        notes.sort(key=lambda item: item.get("updated_at", ""), reverse=True)

        if limit is not None and limit > 0:
            return notes[:limit]
        return notes

    def get_note(self, note_id: str) -> dict[str, Any] | None:
        """按 note_id 读取单条笔记。"""
        note_id = str(note_id).strip()
        if not note_id:
            return None

        for note in self._read_all():
            if str(note.get("id", "")).strip() == note_id:
                return note

        return None

    def add_note(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        kind: str = "note",
        importance: float = 0.5,
        source: str = "manual",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        新增一条结构化笔记。

        importance 用来表示这条笔记的重要程度，
        后面接到上下文工程里时，可以拿它参与排序。
        """
        notes = self._read_all()
        now = self._now()

        note = {
            "id": uuid4().hex,
            "session_id": self.session_id,
            "title": (title or "").strip(),
            "content": (content or "").strip(),
            "tags": tags or [],
            "kind": kind,
            "importance": float(importance),
            "source": source,
            "created_at": now,
            "updated_at": now,
        }

        if extra:
            note["extra"] = extra

        notes.append(note)
        self._write_all(notes)
        return note

    def update_note(
        self,
        note_id: str,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        importance: float | None = None,
        kind: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        更新已有笔记。

        找不到 note_id 时返回 None。
        """
        note_id = str(note_id).strip()
        if not note_id:
            return None

        notes = self._read_all()
        now = self._now()

        for note in notes:
            if str(note.get("id", "")).strip() != note_id:
                continue

            if title is not None:
                note["title"] = title.strip()
            if content is not None:
                note["content"] = content.strip()
            if tags is not None:
                note["tags"] = tags
            if importance is not None:
                note["importance"] = float(importance)
            if kind is not None:
                note["kind"] = kind
            if extra is not None:
                note["extra"] = extra

            note["updated_at"] = now
            self._write_all(notes)
            return note

        return None

    def delete_note(self, note_id: str) -> bool:
        """
        删除一条笔记。

        删除成功返回 True，没找到返回 False。
        """
        note_id = str(note_id).strip()
        if not note_id:
            return False

        notes = self._read_all()
        new_notes = [note for note in notes if str(note.get("id", "")).strip() != note_id]

        if len(new_notes) == len(notes):
            return False

        self._write_all(new_notes)
        return True

    def clear(self) -> None:
        """
        清空当前会话的全部笔记。

        这里直接写空数组，不删除文件。
        """
        self._write_all([])
