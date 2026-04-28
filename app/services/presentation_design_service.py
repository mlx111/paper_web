"""Lightweight design planning for presentation pages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class PresentationDesignService:
    theme_presets = {
        "academic_research": {
            "palette": {
                "background": "#F8FAFC",
                "surface": "#FFFFFF",
                "primary": "#1D4ED8",
                "secondary": "#0F766E",
                "accent": "#D97706",
                "text": "#0F172A",
                "muted": "#64748B",
            },
            "font": {
                "heading": "Source Han Sans SC",
                "body": "Source Han Sans SC",
            },
        },
        "general_story": {
            "palette": {
                "background": "#FFFDF9",
                "surface": "#FFFFFF",
                "primary": "#7C3AED",
                "secondary": "#0EA5E9",
                "accent": "#EA580C",
                "text": "#111827",
                "muted": "#6B7280",
            },
            "font": {
                "heading": "Noto Sans SC",
                "body": "Noto Sans SC",
            },
        },
    }

    def build_design(self, schema: dict[str, Any]) -> dict[str, Any]:
        theme_name = self._select_theme_name(schema)
        theme = self._build_theme(theme_name, schema)
        pages = [self._build_page_design(page, index, len(schema.get("pages", []))) for index, page in enumerate(schema.get("pages", []))]
        return {
            "title": self._clean_text(schema.get("title")) or "Presentation",
            "theme": theme,
            "pages": pages,
            "design_summary": {
                "page_count": len(pages),
                "high_emphasis_pages": [page["page_index"] for page in pages if page.get("emphasis") == "high"],
            },
        }

    def apply_design(self, schema: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(schema)
        design_pages = {page.get("page_index"): page for page in design.get("pages", [])}
        result["design"] = deepcopy(design)
        result["pages"] = [
            {
                **page,
                "design": deepcopy(design_pages.get(page.get("page_index"), {})),
            }
            for page in result.get("pages", [])
        ]
        return result

    def _build_theme(self, theme_name: str, schema: dict[str, Any]) -> dict[str, Any]:
        preset = deepcopy(self.theme_presets[theme_name])
        topic = self._clean_text(schema.get("title"))
        preset.update(
            {
                "name": theme_name,
                "topic": topic,
                "hierarchy": {
                    "title_scale": 1.0,
                    "subtitle_scale": 0.82,
                    "body_scale": 0.68,
                },
                "spacing": {
                    "outer_margin": 44,
                    "section_gap": 20,
                    "line_gap": 12,
                },
            }
        )
        return preset

    def _build_page_design(self, page: dict[str, Any], index: int, total_pages: int) -> dict[str, Any]:
        layout = self._clean_text(page.get("layout"))
        purpose = self._clean_text(page.get("purpose"))
        is_first = index == 0
        is_last = index == total_pages - 1
        role = self._resolve_role(layout, purpose, is_first, is_last)
        emphasis = self._resolve_emphasis(page, role)
        accent = self._resolve_accent(role, index)
        density = self._resolve_density(page)
        whitespace = "spacious" if role in {"hero", "closing"} else ("balanced" if density != "dense" else "compact")
        return {
            "page_index": page.get("page_index"),
            "role": role,
            "emphasis": emphasis,
            "accent": accent,
            "whitespace": whitespace,
            "density": density,
            "layout": layout,
            "purpose": purpose,
        }

    def _resolve_role(self, layout: str, purpose: str, is_first: bool, is_last: bool) -> str:
        if is_first:
            return "hero"
        if is_last or any(token in purpose for token in ("总结", "结论", "展望")):
            return "closing"
        if layout == "image_text":
            return "visual"
        if layout == "two_column":
            return "analysis"
        if layout == "overview":
            return "overview"
        return "content"

    def _resolve_emphasis(self, page: dict[str, Any], role: str) -> str:
        if role in {"hero", "closing"}:
            return "high"
        texts = [self._clean_text(item) for item in page.get("elements", []) if isinstance(item, dict)]
        if any(len(text) > 80 for text in texts if text):
            return "medium"
        return "low"

    def _resolve_accent(self, role: str, index: int) -> str:
        if role == "hero":
            return "primary"
        if role == "closing":
            return "accent"
        return "secondary" if index % 2 == 0 else "primary"

    def _resolve_density(self, page: dict[str, Any]) -> str:
        elements = page.get("elements", [])
        element_count = len(elements) if isinstance(elements, list) else 0
        if element_count >= 8:
            return "dense"
        if element_count >= 5:
            return "balanced"
        return "airy"

    def _select_theme_name(self, schema: dict[str, Any]) -> str:
        source = self._clean_text(schema.get("source")).lower()
        title = self._clean_text(schema.get("title")).lower()
        if source == "research_report" or any(token in title for token in ("survey", "research", "paper", "rag")):
            return "academic_research"
        return "general_story"

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


presentation_design_service = PresentationDesignService()
