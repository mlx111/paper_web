"""Paper review and citation-pool helpers."""

from __future__ import annotations

import re
from typing import Any

from services.academic_tools_service import academic_tools_service


def _ok(**payload: Any) -> dict[str, Any]:
    return {"ok": True, **payload}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


class PaperRefinerService:
    """Safe local refiner utilities for paper reading workflows."""

    def __init__(self, academic_service=None):
        self.academic_service = academic_service or academic_tools_service

    def review_paper_quality(self, paper_text: str, title: str = "") -> dict[str, Any]:
        if not paper_text or len(paper_text.strip()) < 80:
            return _err("INVALID_INPUT", "paper_text is too short for a meaningful review")

        text = paper_text.strip()
        lower = text.lower()
        signals = {
            "abstract": self._has_any(lower, ["abstract", "摘要"]),
            "introduction": self._has_any(lower, ["introduction", "background", "引言", "背景"]),
            "method": self._has_any(lower, ["method", "approach", "algorithm", "方法", "模型"]),
            "experiment": self._has_any(lower, ["experiment", "evaluation", "result", "实验", "评估", "结果"]),
            "conclusion": self._has_any(lower, ["conclusion", "discussion", "结论", "讨论"]),
            "references": self._has_any(lower, ["references", "bibliography", "参考文献"])
            or bool(re.search(r"\[[0-9]{1,3}\]", text)),
        }

        score = 4.0 + sum(0.8 for present in signals.values() if present)
        if len(text) > 2500:
            score += 0.5
        if self._has_any(lower, ["ablation", "baseline", "comparison", "消融", "基线", "对比"]):
            score += 0.5
        score = round(min(score, 10.0), 1)

        strengths = []
        weaknesses = []
        suggestions = []

        if signals["method"]:
            strengths.append("方法或系统设计部分较明确，便于理解论文技术路线。")
        else:
            weaknesses.append("方法描述信号不足，可能难以判断技术方案是否清晰。")
            suggestions.append("补充方法流程、关键模块和算法细节。")

        if signals["experiment"]:
            strengths.append("包含实验或评估相关内容，可以支撑效果判断。")
        else:
            weaknesses.append("实验/评估部分不足，结论可信度会受影响。")
            suggestions.append("增加实验设置、对比基线、指标和误差分析。")

        if signals["references"]:
            strengths.append("包含引用或参考文献信号，有利于定位相关工作。")
        else:
            weaknesses.append("引用信号不足，相关工作支撑可能不够。")
            suggestions.append("补充关键相关工作和引用。")

        missing_sections = [name for name, present in signals.items() if not present]
        if missing_sections:
            suggestions.append("检查并补齐这些结构信号：" + ", ".join(missing_sections) + "。")

        review = {
            "novelty": self._rating_text(score, "创新性"),
            "significance": self._rating_text(score, "研究意义"),
            "soundness": self._rating_text(score if signals["experiment"] else score - 1, "可靠性"),
            "strengths": strengths or ["论文结构具备基本可读性。"],
            "weaknesses": weaknesses or ["当前片段未暴露明显结构性短板。"],
            "suggestions": suggestions or ["进一步强化问题定义、实验细节和相关工作对比。"],
            "detected_sections": signals,
        }
        return _ok(title=title or "Untitled paper", score=score, review=review)

    def build_citation_pool(
        self,
        topic: str,
        max_papers: int = 5,
        engine: str = "openalex",
        include_bibtex: bool = False,
    ) -> dict[str, Any]:
        if not topic or not topic.strip():
            return _err("INVALID_INPUT", "topic must be a non-empty string")

        max_papers = max(1, min(int(max_papers or 5), 10))
        search_result = self.academic_service.search_papers(
            query=topic,
            result_limit=max_papers,
            engine=engine,
        )
        if not search_result.get("ok"):
            return search_result

        citations = []
        seen_titles = set()
        for paper in search_result.get("papers", [])[:max_papers]:
            title = str(paper.get("title") or "").strip()
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())

            item = {
                "title": title,
                "authors": paper.get("authors", ""),
                "year": paper.get("year", ""),
                "venue": paper.get("venue", ""),
                "abstract": paper.get("abstract", ""),
                "url": paper.get("url", ""),
                "citation_count": paper.get("citation_count", 0),
            }

            if include_bibtex and item["url"]:
                bib = self.academic_service.get_bibtex_from_url(item["url"], title)
                if bib.get("ok"):
                    item["bibtex"] = bib.get("bibtex", "")

            citations.append(item)

        return _ok(topic=topic, count=len(citations), citations=citations)

    @staticmethod
    def _has_any(text: str, keywords: list[str]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    @staticmethod
    def _rating_text(score: float, dimension: str) -> str:
        if score >= 8:
            level = "较强"
        elif score >= 6:
            level = "中等"
        else:
            level = "偏弱"
        return f"{dimension}{level}；该判断基于文本结构、实验信号和引用信号的启发式检查。"


paper_refiner_service = PaperRefinerService()
