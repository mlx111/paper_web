from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator
from urllib.parse import quote

try:
    from loguru import logger
except ImportError:  # pragma: no cover - fallback for minimal test environments
    import logging

    logger = logging.getLogger(__name__)

from services.presentation_export_service import PresentationExportService
from services.presentation_layout_service import PresentationLayoutService, presentation_layout_service
from services.presentation_design_service import PresentationDesignService, presentation_design_service
from services.presentation_material_service import PresentationMaterialService, presentation_material_service
from services.presentation_outline_service import PresentationOutlineService, presentation_outline_service
from services.presentation_schema_service import PresentationSchemaService, presentation_schema_service
from tools.websearch_tool import web_search


DEFAULT_STORAGE_ROOT = Path(__file__).resolve().parent.parent / "data" / "presentation"


class PresentationWorkflowService:
    def __init__(
        self,
        storage_root: Path | None = None,
        material_service: PresentationMaterialService | None = None,
        outline_service: PresentationOutlineService | None = None,
        layout_service: PresentationLayoutService | None = None,
        schema_service: PresentationSchemaService | None = None,
        design_service: PresentationDesignService | None = None,
    ):
        self.storage_root = Path(storage_root) if storage_root else DEFAULT_STORAGE_ROOT
        self.export_service = PresentationExportService()
        self.material_service = material_service or presentation_material_service
        self.outline_service = outline_service or presentation_outline_service
        self.layout_service = layout_service or presentation_layout_service
        self.schema_service = schema_service or presentation_schema_service
        self.design_service = design_service or presentation_design_service

    def _build_artifact_paths(self, session_id: str) -> dict[str, Path]:
        session_dir = self.storage_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return {
            "session_dir": session_dir,
            "outline_path": session_dir / "outline.json",
            "layout_path": session_dir / "layout.json",
            "schema_path": session_dir / "schema.json",
            "design_path": session_dir / "design.json",
            "artifact_manifest_path": session_dir / "artifact_manifest.json",
            "quality_report_path": session_dir / "quality_report.json",
            "plan_path": session_dir / "plan.json",
            "manuscript_path": session_dir / "manuscript.md",
            "pptx_path": session_dir / "output.pptx",
            "history_path": session_dir / "history.json",
        }

    def _build_download_urls(self, session_id: str) -> dict[str, str]:
        safe_session_id = quote(session_id, safe="")
        base = f"/presentation/download/{safe_session_id}"
        return {
            "pptx": f"{base}/pptx",
            "plan": f"{base}/plan",
            "manuscript": f"{base}/manuscript",
            "outline": f"{base}/outline",
            "layout": f"{base}/layout",
            "schema": f"{base}/schema",
            "design": f"{base}/design",
            "manifest": f"{base}/manifest",
            "quality": f"{base}/quality",
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

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    def _load_user_materials(self, session_id: str) -> dict[str, Any]:
        try:
            payload = self.material_service.load_materials(session_id)
        except Exception:
            return {
                "session_id": session_id,
                "material_count": 0,
                "materials_path": "",
                "materials": [],
            }
        if not isinstance(payload, dict):
            return {
                "session_id": session_id,
                "material_count": 0,
                "materials_path": "",
                "materials": [],
            }
        payload.setdefault("session_id", session_id)
        payload.setdefault("material_count", len(payload.get("materials") or []))
        payload.setdefault("materials_path", "")
        payload.setdefault("materials", [])
        return payload

    def _material_to_gathered_item(self, material: dict[str, Any]) -> dict[str, Any]:
        title = self._clean_text(material.get("title")) or self._clean_text(material.get("url")) or "User material"
        content = self._clean_text(material.get("content"))
        url = self._clean_text(material.get("url"))
        file_path = self._clean_text(material.get("file_path"))
        snippet = content or url or file_path or title
        return {
            "title": title,
            "snippet": snippet,
            "summary": snippet,
            "content": content,
            "url": url,
            "file_path": file_path,
            "source_type": material.get("source_type") or "paste",
            "material_type": material.get("material_type") or "text",
        }

    def _append_user_material_section(self, manuscript: str, materials: list[dict[str, Any]]) -> str:
        if not materials:
            return manuscript
        lines = ["## 用户素材"]
        for material in materials[:5]:
            title = self._clean_text(material.get("title")) or "未命名素材"
            snippet = (
                self._clean_text(material.get("content"))
                or self._clean_text(material.get("url"))
                or self._clean_text(material.get("file_path"))
            )
            if snippet:
                lines.append(f"- {title}: {snippet}")
            else:
                lines.append(f"- {title}")
        appendix = "\n".join(lines)
        return f"{manuscript}\n\n{appendix}" if manuscript else appendix

    def _load_research_bridge(self, research_session_id: str) -> dict[str, Any]:
        from agents.research_workflow_service import research_workflow_service

        artifacts = research_workflow_service.reload_research_artifacts(research_session_id)
        if not isinstance(artifacts, dict):
            raise ValueError(f"Invalid research artifacts for session: {research_session_id}")
        final_report = str(artifacts.get("final_report") or "").strip()
        if not final_report:
            raise ValueError(f"Missing research final report for session: {research_session_id}")
        return artifacts

    def _outline_from_plan(self, topic: str, gathered: list[dict[str, Any]], target_pages: int | None = None) -> dict[str, Any]:
        return self.outline_service.build_outline(
            topic=topic,
            gathered=gathered,
            target_pages=target_pages,
        )

    def _apply_layouts(self, outline: dict[str, Any]) -> dict[str, Any]:
        return self.layout_service.select_layouts(outline)

    def _build_schema(self, layout: dict[str, Any]) -> dict[str, Any]:
        return self.schema_service.build_schema(layout)

    def _build_design(self, schema: dict[str, Any]) -> dict[str, Any]:
        return self.design_service.build_design(schema)

    def _build_artifact_manifest(
        self,
        session_id: str,
        resolved_topic: str,
        outline: dict[str, Any],
        layout: dict[str, Any],
        schema: dict[str, Any],
        design: dict[str, Any],
        paths: dict[str, Path],
        download_urls: dict[str, str],
        research_session_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "topic": resolved_topic,
            "research_session_id": research_session_id or "",
            "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "artifacts": {
                "outline_path": str(paths["outline_path"]),
                "layout_path": str(paths["layout_path"]),
                "schema_path": str(paths["schema_path"]),
                "design_path": str(paths["design_path"]),
                "quality_report_path": str(paths["quality_report_path"]),
                "plan_path": str(paths["plan_path"]),
                "manuscript_path": str(paths["manuscript_path"]),
                "pptx_path": str(paths["pptx_path"]),
            },
            "download_urls": download_urls,
            "summary": {
                "outline_pages": len(outline.get("pages", [])),
                "layout_pages": len(layout.get("pages", [])),
                "schema_pages": len(schema.get("pages", [])),
                "designed_pages": len(design.get("pages", [])),
                "theme": (design.get("theme") or {}).get("name", ""),
            },
        }

    def _plan_from_research_report(
        self,
        topic: str,
        report_text: str,
        target_pages: int | None = None,
        user_materials: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        outline = self.outline_service.build_outline(
            topic=topic,
            gathered=[],
            target_pages=target_pages,
            research_report_text=report_text,
            user_materials=user_materials,
        )
        return self.outline_service.outline_to_plan(outline)

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
                str(snippet)[:120] if snippet else "结合已知信息整理核心内容",
            ]
            slides.append({"title": title, "bullets": [bullet for bullet in bullets if bullet]})
        return {
            "title": topic,
            "audience": "general",
            "slides": slides,
        }

    def _infer_page_count(self, target_pages: int | None, gathered: list[dict[str, Any]]) -> int:
        if target_pages and target_pages > 0:
            return target_pages
        if len(gathered) >= 6:
            return 6
        if len(gathered) >= 3:
            return 5
        return 4

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

    def _read_json_file(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _read_text_file(self, path: Path, default: str = "") -> str:
        if not path.exists():
            return default
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return default

    def _load_presentation_artifacts(self, session_id: str) -> dict[str, Any]:
        paths = self._build_artifact_paths(session_id)
        return {
            "paths": {key: str(value) for key, value in paths.items()},
            "outline": self._read_json_file(paths["outline_path"], {}),
            "layout": self._read_json_file(paths["layout_path"], {}),
            "schema": self._read_json_file(paths["schema_path"], {}),
            "design": self._read_json_file(paths["design_path"], {}),
            "manifest": self._read_json_file(paths["artifact_manifest_path"], {}),
            "quality_report": self._read_json_file(paths["quality_report_path"], {}),
            "plan": self._read_json_file(paths["plan_path"], {}),
            "manuscript": self._read_text_file(paths["manuscript_path"], ""),
            "pptx_exists": paths["pptx_path"].exists(),
            "pptx_size": paths["pptx_path"].stat().st_size if paths["pptx_path"].exists() else 0,
        }

    def _build_quality_report(self, session_id: str, artifacts: dict[str, Any]) -> dict[str, Any]:
        outline = artifacts.get("outline") or {}
        layout = artifacts.get("layout") or {}
        schema = artifacts.get("schema") or {}
        design = artifacts.get("design") or {}
        plan = artifacts.get("plan") or {}
        manifest = artifacts.get("manifest") or {}
        manuscript = str(artifacts.get("manuscript") or "")

        issues: list[str] = []
        warnings: list[str] = []
        checks: dict[str, bool] = {}

        required_counts = {
            "outline_pages": len(outline.get("pages", [])) if isinstance(outline, dict) else 0,
            "layout_pages": len(layout.get("pages", [])) if isinstance(layout, dict) else 0,
            "schema_pages": len(schema.get("pages", [])) if isinstance(schema, dict) else 0,
            "design_pages": len(design.get("pages", [])) if isinstance(design, dict) else 0,
            "plan_slides": len(plan.get("slides", [])) if isinstance(plan, dict) else 0,
        }
        counts = list(required_counts.values())
        aligned = all(count == counts[0] for count in counts if count > 0) if counts else False
        checks["artifact_count_alignment"] = aligned
        if not aligned:
            issues.append("Artifact page counts are not aligned across outline/layout/schema/design/plan.")

        pptx_exists = bool(artifacts.get("pptx_exists"))
        pptx_size = int(artifacts.get("pptx_size") or 0)
        checks["pptx_exists"] = pptx_exists and pptx_size > 0
        if not pptx_exists:
            issues.append("Missing output.pptx artifact.")
        elif pptx_size <= 0:
            issues.append("output.pptx is empty.")

        manifest_summary = manifest.get("summary") if isinstance(manifest, dict) else {}
        if isinstance(manifest_summary, dict):
            expected_outline = int(manifest_summary.get("outline_pages") or 0)
            expected_layout = int(manifest_summary.get("layout_pages") or 0)
            expected_schema = int(manifest_summary.get("schema_pages") or 0)
            expected_design = int(manifest_summary.get("designed_pages") or 0)
            if expected_outline and expected_outline != required_counts["outline_pages"]:
                issues.append("Manifest outline page count does not match outline.json.")
            if expected_layout and expected_layout != required_counts["layout_pages"]:
                issues.append("Manifest layout page count does not match layout.json.")
            if expected_schema and expected_schema != required_counts["schema_pages"]:
                issues.append("Manifest schema page count does not match schema.json.")
            if expected_design and expected_design != required_counts["design_pages"]:
                issues.append("Manifest design page count does not match design.json.")

        slide_placeholder_tokens = {
            "bridge",
            "draft",
            "debug",
            "todo",
            "tbd",
            "placeholder",
        }
        manuscript_placeholder_tokens = slide_placeholder_tokens | {
            "plan",
            "research process",
            "内容待补充",
            "待补充",
            "研究过程",
            "研究阶段",
            "研究计划",
        }
        text_sources: list[tuple[str, str]] = []
        for slide in plan.get("slides", []) if isinstance(plan, dict) else []:
            if isinstance(slide, dict):
                text_sources.append(("slide title", self._clean_text(slide.get("title"))))
                for bullet in slide.get("bullets", []):
                    text_sources.append(("slide bullet", self._clean_text(bullet)))

        for line in manuscript.splitlines():
            cleaned = self._clean_text(line)
            if cleaned:
                text_sources.append(("manuscript", cleaned))

        for source_name, text in text_sources:
            lowered = text.lower()
            if not text:
                continue
            tokens = manuscript_placeholder_tokens if source_name == "manuscript" else slide_placeholder_tokens
            if any(token == lowered or token in lowered for token in tokens):
                if source_name == "manuscript":
                    warnings.append(f"Potential internal-stage text found in manuscript: {text[:120]}")
                else:
                    issues.append(f"Placeholder or debug text found in {source_name}: {text[:120]}")
            if source_name == "slide bullet" and len(text) > 160:
                issues.append(f"Slide bullet is too long ({len(text)} chars): {text[:120]}")
            if source_name == "slide title" and len(text) > 80:
                warnings.append(f"Slide title is long ({len(text)} chars): {text[:120]}")
            if source_name == "manuscript" and len(text) > 220:
                warnings.append(f"Long manuscript line detected ({len(text)} chars): {text[:120]}")
            if source_name == "manuscript" and ("{\"" in text or "\"}" in text or "{debug" in lowered):
                warnings.append(f"Structured/debug-like text found in manuscript: {text[:120]}")

        checks["content_clean"] = not any("Placeholder or debug text" in issue for issue in issues)
        checks["length_clean"] = not any("too long" in issue for issue in issues)

        quality = {
            "session_id": session_id,
            "report_version": "v1.6",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "passed": not issues,
            "issues": issues,
            "warnings": warnings,
            "checks": checks,
            "summary": {
                **required_counts,
                "pptx_exists": pptx_exists,
                "pptx_size": pptx_size,
                "quality_source": "presentation_artifacts",
            },
            "paths": artifacts.get("paths", {}),
        }
        return quality

    def _write_quality_report(self, paths: dict[str, Path], quality_report: dict[str, Any]) -> str:
        quality_path = paths["quality_report_path"]
        quality_path.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(quality_path)

    def check_quality(self, session_id: str) -> dict[str, Any]:
        artifacts = self._load_presentation_artifacts(session_id)
        quality = self._build_quality_report(session_id, artifacts)
        paths = self._build_artifact_paths(session_id)
        quality["quality_report_path"] = self._write_quality_report(paths, quality)
        return quality

    def _finalize_presentation_bundle(
        self,
        session_id: str,
        resolved_topic: str,
        outline: dict[str, Any],
        layout: dict[str, Any],
        schema: dict[str, Any],
        design: dict[str, Any],
        plan: dict[str, Any],
        manuscript: str,
        research_session_id: str | None = None,
        source_report_path: str = "",
    ) -> dict[str, Any]:
        paths = self._build_artifact_paths(session_id)
        paths["outline_path"].write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["layout_path"].write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["schema_path"].write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["design_path"].write_text(json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["plan_path"].write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["manuscript_path"].write_text(manuscript, encoding="utf-8")
        self.export_service.export(plan=plan, manuscript=manuscript, output_path=paths["pptx_path"])

        download_urls = self._build_download_urls(session_id)
        manifest = self._build_artifact_manifest(
            session_id=session_id,
            resolved_topic=resolved_topic,
            outline=outline,
            layout=layout,
            schema=schema,
            design=design,
            paths=paths,
            download_urls=download_urls,
            research_session_id=research_session_id,
        )
        paths["artifact_manifest_path"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        quality_report = self.check_quality(session_id)
        artifacts = {
            "session_id": session_id,
            "outline_path": str(paths["outline_path"]),
            "layout_path": str(paths["layout_path"]),
            "schema_path": str(paths["schema_path"]),
            "design_path": str(paths["design_path"]),
            "manifest_path": str(paths["artifact_manifest_path"]),
            "quality_report_path": str(paths["quality_report_path"]),
            "plan_path": str(paths["plan_path"]),
            "manuscript_path": str(paths["manuscript_path"]),
            "pptx_path": str(paths["pptx_path"]),
            "download_urls": download_urls,
            "title": resolved_topic,
            "topic": resolved_topic,
            "outline": outline,
            "layout": layout,
            "schema": schema,
            "design": design,
            "research_session_id": research_session_id or "",
            "source_report_path": source_report_path,
            "source_report_version": "",
            "quality_report": quality_report,
        }
        return artifacts

    def regenerate_from_artifacts(self, session_id: str) -> dict[str, Any]:
        artifacts = self._load_presentation_artifacts(session_id)
        outline = artifacts.get("outline") or {}
        layout = artifacts.get("layout") or {}
        schema = artifacts.get("schema") or {}
        design = artifacts.get("design") or {}
        manifest = artifacts.get("manifest") or {}

        if not outline or not layout or not schema or not design:
            raise ValueError(f"Missing saved presentation artifacts for session: {session_id}")

        resolved_topic = self._clean_text(manifest.get("topic")) or self._clean_text(outline.get("title")) or "Presentation"
        research_session_id = self._clean_text(manifest.get("research_session_id"))
        designed_schema = self.design_service.apply_design(schema, design)
        plan = self.schema_service.schema_to_plan(designed_schema)
        manuscript = str(artifacts.get("manuscript") or "") or self._draft(plan)
        source_report_path = self._clean_text((manifest.get("artifacts") or {}).get("report_path")) or ""
        regenerated = self._finalize_presentation_bundle(
            session_id=session_id,
            resolved_topic=resolved_topic,
            outline=outline,
            layout=layout,
            schema=schema,
            design=design,
            plan=plan,
            manuscript=manuscript,
            research_session_id=research_session_id or None,
            source_report_path=source_report_path,
        )
        regenerated["source_report_version"] = str(manifest.get("report_version") or "")
        regenerated["regenerated_from_artifacts"] = True
        result = {
            "answer": f"已基于保存的演示工件重新生成“{resolved_topic}”的 PPT。",
            "artifacts": regenerated,
            **regenerated,
        }
        self._write_history(self._build_artifact_paths(session_id)["history_path"], resolved_topic, result)
        return result

    def run_topic(
        self,
        session_id: str,
        topic: str | None,
        target_pages: int | None = None,
        research_session_id: str | None = None,
    ) -> dict[str, str]:
        paths = self._build_artifact_paths(session_id)
        user_materials = self._load_user_materials(session_id)
        materials = list(user_materials.get("materials") or [])
        material_gathered = [self._material_to_gathered_item(material) for material in materials]
        research_artifacts: dict[str, Any] | None = None
        source_report_path = ""

        if research_session_id:
            research_artifacts = self._load_research_bridge(research_session_id)
            report_text = str(research_artifacts.get("final_report") or "").strip()
            source_report_path = str((research_artifacts.get("paths") or {}).get("final_report") or "")
            manifest = research_artifacts.get("manifest") or {}
            resolved_topic = self._clean_text(topic) or self._clean_text(manifest.get("question")) or "Research presentation"
            outline = self.outline_service.build_outline(
                topic=resolved_topic,
                gathered=material_gathered,
                target_pages=target_pages,
                research_report_text=report_text,
                user_materials=materials,
            )
            layout = self._apply_layouts(outline)
            schema = self._build_schema(layout)
            design = self._build_design(schema)
            designed_schema = self.design_service.apply_design(schema, design)
            plan = self.schema_service.schema_to_plan(designed_schema)
            manuscript = report_text
        else:
            resolved_topic = self._clean_text(topic) or "Presentation"
            meta = self._classify_topic(resolved_topic)
            gathered = material_gathered + self._gather(resolved_topic, use_web_search=meta["use_web_search"])
            outline = self.outline_service.build_outline(
                topic=resolved_topic,
                gathered=gathered,
                target_pages=target_pages,
                user_materials=materials,
            )
            layout = self._apply_layouts(outline)
            schema = self._build_schema(layout)
            design = self._build_design(schema)
            designed_schema = self.design_service.apply_design(schema, design)
            plan = self.schema_service.schema_to_plan(designed_schema)
            manuscript = self._draft(plan)

        manuscript = self._append_user_material_section(manuscript, materials)
        artifacts = self._finalize_presentation_bundle(
            session_id=session_id,
            resolved_topic=resolved_topic,
            outline=outline,
            layout=layout,
            schema=schema,
            design=design,
            plan=plan,
            manuscript=manuscript,
            research_session_id=research_session_id,
            source_report_path=source_report_path,
        )

        if research_session_id:
            answer = (
                "已基于研究报告生成演示初稿，"
                f"共生成 {len(plan.get('slides', []))} 页大纲，"
                "并输出了 plan、manuscript 和 pptx 文件。"
            )
        else:
            answer = (
                f"已完成主题“{resolved_topic}”的演示初稿生成，"
                f"共生成 {len(plan.get('slides', []))} 页大纲，"
                "并输出了 plan、manuscript 和 pptx 文件。"
            )

        artifacts["source_report_version"] = str((research_artifacts or {}).get("manifest", {}).get("report_version", ""))
        artifacts["materials_path"] = str(user_materials.get("materials_path") or "")
        artifacts["materials_count"] = int(user_materials.get("material_count") or 0)
        artifacts["materials"] = materials
        result = {
            "answer": answer,
            "artifacts": artifacts,
            **artifacts,
        }
        self._write_history(paths["history_path"], resolved_topic, result)
        return result

    async def query_stream(self, request) -> AsyncGenerator[dict[str, Any], None]:
        logger.info("[presentation {}] start topic: {}", request.session_id, request.topic)
        if getattr(request, "research_session_id", None):
            yield {"type": "debug", "data": "bridge"}
            yield {"type": "content", "data": "正在读取研究报告并抽取演示结构...\n"}
            yield {"type": "debug", "data": "outline"}
            yield {"type": "content", "data": "正在生成结构化大纲...\n"}
            yield {"type": "debug", "data": "plan"}
            yield {"type": "content", "data": "正在整理页面大纲为幻灯片计划...\n"}
            yield {"type": "debug", "data": "draft"}
            yield {"type": "content", "data": "正在输出 Markdown 讲稿并导出 PPT...\n"}
            result = self.run_topic(
                request.session_id,
                getattr(request, "topic", None),
                getattr(request, "target_pages", None),
                research_session_id=getattr(request, "research_session_id", None),
            )
        else:
            yield {"type": "debug", "data": "classify"}
            yield {"type": "content", "data": "正在分析主题定位...\n"}
            yield {"type": "debug", "data": "gather"}
            yield {"type": "content", "data": "正在整理网页与素材信息...\n"}
            yield {"type": "debug", "data": "outline"}
            yield {"type": "content", "data": "正在生成结构化大纲...\n"}
            yield {"type": "debug", "data": "plan"}
            yield {"type": "content", "data": "正在生成页面级演示计划...\n"}
            yield {"type": "debug", "data": "draft"}
            yield {"type": "content", "data": "正在输出 Markdown 讲稿并导出 PPT...\n"}
            result = self.run_topic(request.session_id, getattr(request, "topic", None), getattr(request, "target_pages", None))
        yield {"type": "complete", "data": result}

    def clear_session(self, session_id: str) -> bool:
        session_dir = self.storage_root / session_id
        try:
            self.material_service.clear_session_materials(session_id)
        except Exception:
            pass
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
