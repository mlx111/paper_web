"""Structured outline generation for presentation workflow."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


class PresentationOutlineService:
    noise_tokens = {
        "bridge",
        "plan",
        "draft",
        "debug",
        "研究过程",
        "研究计划",
        "research process",
    }

    default_purposes = [
        "封面与概览",
        "背景与问题",
        "核心观点",
        "关键证据",
        "实践建议",
        "总结与展望",
    ]

    research_purposes = [
        "研究概览",
        "研究方向",
        "核心发现",
        "来源概览",
        "结论与建议",
    ]

    def build_outline(
        self,
        topic: str,
        gathered: list[dict[str, Any]] | None = None,
        target_pages: int | None = None,
        research_report_text: str | None = None,
        user_materials: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        topic = self._clean_text(topic) or "Presentation"
        gathered = list(gathered or [])
        materials = list(user_materials or [])
        source_items = self._collect_source_items(gathered, materials)
        research_sections = self._extract_research_sections(research_report_text or "")

        page_count = max(2, int(target_pages) if target_pages and int(target_pages) > 0 else self._infer_page_count(source_items))
        purposes = self.research_purposes if research_sections else self.default_purposes

        pages: list[dict[str, Any]] = []
        for index in range(page_count):
            purpose = purposes[index] if index < len(purposes) else f"扩展页 {index + 1}"
            section_bullets = research_sections[index]["bullets"] if index < len(research_sections) else []
            indexes = self._build_indexes(index, source_items, section_bullets)
            images = self._collect_images(gathered, materials)
            pages.append(
                {
                    "page_index": index + 1,
                    "purpose": purpose,
                    "topic": topic,
                    "indexes": indexes,
                    "images": images if index == 0 else [],
                }
            )

        return {
            "title": topic,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "research_report" if research_sections else "gathered_sources",
            "pages": pages,
        }

    def outline_to_plan(self, outline: dict[str, Any]) -> dict[str, Any]:
        slides: list[dict[str, Any]] = []
        for page in outline.get("pages", []):
            bullets = self._deduplicate(
                [
                    self._clean_text(page.get("topic")),
                    *[self._clean_text(item) for item in page.get("indexes", [])],
                ]
            )
            slides.append(
                {
                    "title": self._clean_text(page.get("purpose")) or "Slide",
                    "bullets": bullets or ["内容待补充"],
                    "images": list(page.get("images") or []),
                }
            )
        return {
            "title": self._clean_text(outline.get("title")) or "Presentation",
            "audience": outline.get("source", "general"),
            "slides": slides,
            "outline": outline,
        }

    def _collect_source_items(self, gathered: list[dict[str, Any]], materials: list[dict[str, Any]]) -> list[str]:
        items: list[str] = []
        for entry in gathered + materials:
            for value in (
                entry.get("snippet"),
                entry.get("summary"),
                entry.get("content"),
                entry.get("title"),
                entry.get("url"),
                entry.get("file_path"),
            ):
                text = self._clean_text(value)
                if text:
                    items.extend(self._split_source_text(text))
                    break
        return self._deduplicate([item for item in items if not self._is_noise(item)])

    def _collect_images(self, gathered: list[dict[str, Any]], materials: list[dict[str, Any]]) -> list[str]:
        images: list[str] = []
        for entry in gathered + materials:
            material_type = self._clean_text(entry.get("material_type") or entry.get("materialType"))
            if material_type != "image":
                continue
            for value in (entry.get("file_path"), entry.get("url"), entry.get("title")):
                text = self._clean_text(value)
                if text:
                    images.append(text)
                    break
        return self._deduplicate(images)

    def _build_indexes(self, page_index: int, source_items: list[str], section_bullets: list[str]) -> list[str]:
        indexes: list[str] = []
        indexes.extend([item for item in section_bullets if self._clean_text(item) and not self._is_noise(item)])
        if not indexes:
            indexes.extend(source_items[page_index * 2 : page_index * 2 + 2])
        if not indexes:
            indexes.append("内容待补充")
        return self._deduplicate([self._clean_text(item) for item in indexes if self._clean_text(item)])[:4]

    def _extract_research_sections(self, report_text: str) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for raw_line in report_text.splitlines():
            line = self._clean_text(raw_line)
            if not line or self._is_noise(line):
                continue
            if line.startswith("## "):
                if current:
                    sections.append(current)
                current = {"title": line[3:].strip(), "bullets": []}
                continue
            if current is None:
                continue
            if line.startswith("- "):
                current.setdefault("bullets", []).append(self._clean_text(line[2:]))
            elif not line.startswith("#"):
                current.setdefault("bullets", []).append(line)
        if current:
            sections.append(current)
        return sections

    def _split_source_text(self, text: str) -> list[str]:
        parts = [part.strip() for part in re.split(r"[。\n\r;；]+", text) if part.strip()]
        if len(parts) > 1:
            return parts
        return [text.strip()]

    def _infer_page_count(self, source_items: list[str]) -> int:
        if len(source_items) >= 8:
            return 6
        if len(source_items) >= 4:
            return 5
        return 4

    def _is_noise(self, text: str) -> bool:
        lowered = text.lower()
        if not lowered:
            return True
        if lowered.startswith("{") or lowered.startswith("}") or lowered.startswith("["):
            return True
        return any(token in lowered for token in self.noise_tokens)

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @staticmethod
    def _deduplicate(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped


presentation_outline_service = PresentationOutlineService()
