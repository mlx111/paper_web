from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncGenerator

from loguru import logger

from services.presentation_export_service import PresentationExportService
from tools.websearch_tool import web_search


DEFAULT_STORAGE_ROOT = Path(__file__).resolve().parent.parent / "data" / "presentation"


class PresentationWorkflowService:
    def __init__(self, storage_root: Path | None = None):
        self.storage_root = Path(storage_root) if storage_root else DEFAULT_STORAGE_ROOT
        self.export_service = PresentationExportService()

    def _build_artifact_paths(self, session_id: str) -> dict[str, Path]:
        session_dir = self.storage_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return {
            "session_dir": session_dir,
            "plan_path": session_dir / "plan.json",
            "manuscript_path": session_dir / "manuscript.md",
            "pptx_path": session_dir / "output.pptx",
            "history_path": session_dir / "history.json",
        }

    def _classify_topic(self, topic: str) -> dict[str, Any]:
        topic_lower = topic.lower()
        academic_terms = (
            "paper",
            "papers",
            "research",
            "survey",
            "rag",
            "method",
            "model",
            "论文",
            "研究",
            "综述",
            "模型",
            "方法",
        )
        if any(term in topic_lower for term in academic_terms):
            return {
                "category": "academic_technical",
                "use_web_search": True,
                "use_academic_research": True,
            }
        return {
            "category": "general_presentation",
            "use_web_search": True,
            "use_academic_research": False,
        }

    def _web_search(self, query: str):
        return web_search(query=query)

    def _gather(self, topic: str, use_web_search: bool = True) -> list[dict[str, Any]]:
        if not use_web_search:
            return []

        result = self._web_search(topic) or {}
        if isinstance(result, dict):
            candidates = result.get("data") or result.get("results") or result.get("items") or result.get("documents")
            if isinstance(candidates, list):
                return [item for item in candidates if isinstance(item, dict)]
            summary = result.get("summary")
            if summary:
                return [{"title": topic, "snippet": str(summary)}]
            if result.get("error"):
                return [{"title": topic, "snippet": str(result["error"])}]
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []

    def _infer_page_count(self, target_pages: int | None, gathered: list[dict[str, Any]]) -> int:
        if target_pages and target_pages > 0:
            return target_pages
        if len(gathered) >= 6:
            return 6
        if len(gathered) >= 3:
            return 5
        return 4

    def _plan(self, topic: str, gathered: list[dict[str, Any]], target_pages: int | None = None) -> dict[str, Any]:
        page_count = self._infer_page_count(target_pages, gathered)
        default_titles = [
            "主题概览",
            "背景与问题",
            "核心思路",
            "关键要点",
            "实践建议",
            "总结",
        ]
        gathered_snippets = [
            item.get("snippet") or item.get("summary") or item.get("content") or item.get("title") or ""
            for item in gathered
        ]
        slides = []
        for index in range(page_count):
            title = default_titles[index] if index < len(default_titles) else f"扩展页 {index + 1}"
            snippet = gathered_snippets[index % len(gathered_snippets)] if gathered_snippets else ""
            bullets = [
                f"围绕“{topic}”展开第 {index + 1} 页内容",
                str(snippet)[:120] if snippet else "结合已有知识整理核心信息",
            ]
            slides.append({"title": title, "bullets": [bullet for bullet in bullets if bullet]})
        return {
            "title": topic,
            "audience": "general",
            "slides": slides,
        }

    def _draft(self, plan: dict[str, Any]) -> str:
        sections: list[str] = []
        for slide in plan.get("slides", []):
            bullets = "\n".join(f"- {item}" for item in slide.get("bullets", []))
            sections.append(f"# {slide.get('title', 'Slide')}\n\n{bullets}".strip())
        return "\n\n---\n\n".join(section for section in sections if section)

    def _write_history(self, history_path: Path, topic: str, result: dict[str, str]) -> None:
        history = [
            {"type": "user", "content": topic},
            {
                "type": "assistant",
                "content": result.get("answer", "Presentation generation completed."),
                "artifacts": result,
            },
        ]
        history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_topic(self, session_id: str, topic: str, target_pages: int | None = None) -> dict[str, str]:
        paths = self._build_artifact_paths(session_id)
        meta = self._classify_topic(topic)
        gathered = self._gather(topic, use_web_search=meta["use_web_search"])
        plan = self._plan(topic, gathered, target_pages=target_pages)
        manuscript = self._draft(plan)
        paths["plan_path"].write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["manuscript_path"].write_text(manuscript, encoding="utf-8")
        self.export_service.export(plan=plan, manuscript=manuscript, output_path=paths["pptx_path"])
        answer = (
            f"已完成《{topic}》的演示初稿生成，"
            f"共生成 {len(plan.get('slides', []))} 页大纲，"
            "并输出了 plan、manuscript 和 pptx 文件。"
        )
        result = {
            "answer": answer,
            "plan_path": str(paths["plan_path"]),
            "manuscript_path": str(paths["manuscript_path"]),
            "pptx_path": str(paths["pptx_path"]),
        }
        self._write_history(paths["history_path"], topic, result)
        return result

    async def query_stream(self, request) -> AsyncGenerator[dict[str, Any], None]:
        logger.info("[presentation {}] start topic: {}", request.session_id, request.topic)
        yield {"type": "debug", "data": "classify"}
        yield {"type": "content", "data": "正在分析主题定位...\n"}
        yield {"type": "debug", "data": "gather"}
        yield {"type": "content", "data": "正在整理网页搜索资料...\n"}
        yield {"type": "debug", "data": "plan"}
        yield {"type": "content", "data": "正在生成页级演示大纲...\n"}
        yield {"type": "debug", "data": "draft"}
        yield {"type": "content", "data": "正在输出 Markdown 讲稿并导出 PPT...\n"}
        result = self.run_topic(request.session_id, request.topic, request.target_pages)
        yield {"type": "complete", "data": result}

    def clear_session(self, session_id: str) -> bool:
        session_dir = self.storage_root / session_id
        if not session_dir.exists():
            return True
        for item in sorted(session_dir.rglob("*"), reverse=True):
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
        session_dir.rmdir()
        return True

    def get_session_history(self, session_id: str) -> list[dict[str, Any]]:
        history_path = self.storage_root / session_id / "history.json"
        if not history_path.exists():
            return []
        try:
            return json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            return []


presentation_workflow_service = PresentationWorkflowService()
