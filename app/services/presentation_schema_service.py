"""Element-level schema generation for presentation pages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class PresentationSchemaService:
    noise_tokens = {
        "bridge",
        "plan",
        "draft",
        "debug",
        "research process",
    }

    def build_schema(self, layout: dict[str, Any]) -> dict[str, Any]:
        pages = [self._build_page_schema(page) for page in layout.get("pages", [])]
        return {
            "title": self._clean_text(layout.get("title")) or "Presentation",
            "source": layout.get("source", "general"),
            "pages": pages,
            "layout_summary": layout.get("layout_summary", {}),
        }

    def schema_to_plan(self, schema: dict[str, Any]) -> dict[str, Any]:
        slides: list[dict[str, Any]] = []
        for page in schema.get("pages", []):
            bullets: list[str] = []
            for element in page.get("elements", []):
                if element.get("type") in {"title", "subtitle", "bullet", "citation", "caption"}:
                    text = self._clean_text(element.get("text"))
                    if text and text not in bullets:
                        bullets.append(text)
            if not bullets:
                bullets = ["内容待补充"]
            slides.append(
                {
                    "title": self._clean_text(page.get("purpose")) or self._clean_text(page.get("topic")) or "Slide",
                    "bullets": bullets[:5],
                    "elements": page.get("elements", []),
                    "layout": page.get("layout", "single_column_text"),
                }
            )
        return {
            "title": self._clean_text(schema.get("title")) or "Presentation",
            "audience": schema.get("source", "general"),
            "slides": slides,
            "schema": deepcopy(schema),
        }

    def _build_page_schema(self, page: dict[str, Any]) -> dict[str, Any]:
        purpose = self._clean_text(page.get("purpose"))
        topic = self._clean_text(page.get("topic"))
        layout = self._clean_text(page.get("layout")) or "single_column_text"
        indexes = [
            self._clean_text(item)
            for item in page.get("indexes", [])
            if self._clean_text(item) and not self._is_noise(self._clean_text(item))
        ]
        images = [self._clean_text(item) for item in page.get("images", []) if self._clean_text(item)]

        elements: list[dict[str, Any]] = [
            self._element("title", topic or purpose, 42),
            self._element("subtitle", purpose or topic, 60),
        ]

        for index in indexes[:4]:
            elements.append(self._element("bullet", self._trim_text(index, 80), 80))

        if indexes:
            citation_text = f"来源：{topic or 'Presentation'} / {purpose or 'Page'}"
            if not self._is_noise(citation_text):
                elements.append(self._element("citation", citation_text, 80))

        for image in images[:2]:
            elements.append(self._element("image", image, 80))
            elements.append(self._element("caption", f"图：{self._caption_from_image(image, purpose)}", 70))

        return {
            "page_index": page.get("page_index"),
            "purpose": purpose,
            "topic": topic,
            "layout": layout,
            "elements": elements,
        }

    def _element(self, element_type: str, text: str, max_chars: int) -> dict[str, Any]:
        return {
            "type": element_type,
            "text": self._trim_text(text, max_chars),
            "max_chars": max_chars,
        }

    def _caption_from_image(self, image: str, purpose: str) -> str:
        base = self._clean_text(purpose) or "插图"
        if image:
            return f"{base}中的参考图"
        return base

    def _trim_text(self, text: str, max_chars: int) -> str:
        cleaned = self._clean_text(text)
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[: max(0, max_chars - 1)].rstrip() + "…"

    def _is_noise(self, text: str) -> bool:
        lowered = self._clean_text(text).lower()
        if not lowered:
            return True
        if lowered.startswith("{") or lowered.startswith("["):
            return True
        return any(token in lowered for token in self.noise_tokens)

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


presentation_schema_service = PresentationSchemaService()
