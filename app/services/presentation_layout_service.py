"""Layout selection for presentation pages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class PresentationLayoutService:
    dense_threshold = 4
    long_text_threshold = 110

    def select_layout_for_page(self, page: dict[str, Any], is_first: bool = False, is_last: bool = False) -> dict[str, Any]:
        purpose = self._clean_text(page.get("purpose"))
        indexes = [self._clean_text(item) for item in page.get("indexes", []) if self._clean_text(item)]
        images = [self._clean_text(item) for item in page.get("images", []) if self._clean_text(item)]
        text_length = sum(len(item) for item in indexes)

        if is_first:
            layout = "cover"
            reason = "first slide"
        elif is_last and self._looks_like_closing(purpose):
            layout = "closing"
            reason = "closing slide"
        elif images and len(indexes) <= 3:
            layout = "image_text"
            reason = "visual page with images"
        elif len(indexes) >= self.dense_threshold or (len(indexes) >= 2 and text_length >= self.long_text_threshold):
            layout = "two_column"
            reason = "dense content"
        elif self._looks_like_overview(purpose):
            layout = "overview"
            reason = "overview page"
        else:
            layout = "single_column_text"
            reason = "default text page"

        return {
            **page,
            "layout": layout,
            "layout_reason": reason,
            "reason": reason,
        }

    def select_layouts(self, outline: dict[str, Any]) -> dict[str, Any]:
        pages = list(outline.get("pages", []))
        selected_pages = [
            self.select_layout_for_page(page, is_first=index == 0, is_last=index == len(pages) - 1)
            for index, page in enumerate(pages)
        ]
        result = deepcopy(outline)
        result["pages"] = selected_pages
        result["layout_summary"] = {
            "page_count": len(selected_pages),
            "layouts": [page.get("layout") for page in selected_pages],
        }
        return result

    @staticmethod
    def _looks_like_closing(purpose: str) -> bool:
        return any(token in purpose for token in ("总结", "结论", "展望", "closing"))

    @staticmethod
    def _looks_like_overview(purpose: str) -> bool:
        return any(token in purpose for token in ("概览", "总览", "overview"))

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


presentation_layout_service = PresentationLayoutService()
