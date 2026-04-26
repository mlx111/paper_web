"""Parse PDF/DOCX documents while preserving image placeholders."""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    from langchain_core.documents import Document
except Exception:  # pragma: no cover - fallback for lightweight test envs
    class Document:  # type: ignore[no-redef]
        def __init__(self, page_content: str, metadata: dict[str, Any] | None = None):
            self.page_content = page_content
            self.metadata = metadata or {}

from services.chunk_image_store_service import (
    ChunkImageStore,
    default_chunk_image_store,
    extract_image_placeholders,
)


_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg_rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


class DocumentImageParserService:
    def __init__(
        self,
        image_store: ChunkImageStore = default_chunk_image_store,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
    ):
        self.image_store = image_store
        self.chunk_size = chunk_size
        self.chunk_overlap = max(0, min(chunk_overlap, chunk_size // 2))

    def parse(self, file_path: str, filename: str | None = None) -> list[Document]:
        path = Path(file_path)
        name = filename or path.name
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return self._parse_docx(path, name)
        if suffix == ".pdf":
            return self._parse_pdf(path, name)
        raise ValueError(f"不支持图文解析的文件类型: {path.suffix}")

    def _parse_docx(self, path: Path, filename: str) -> list[Document]:
        with zipfile.ZipFile(path) as package:
            document_xml = package.read("word/document.xml")
            relationships = self._read_docx_relationships(package)
            root = ET.fromstring(document_xml)
            body = root.find("w:body", _NS)
            if body is None:
                return []

            docs: list[Document] = []
            buffer = ""
            chunk_index = 0

            def new_chunk_id(index: int) -> str:
                return f"{filename}::image::0::{index}"

            current_chunk_id = new_chunk_id(chunk_index)

            def seal() -> None:
                nonlocal buffer, chunk_index, current_chunk_id
                content = buffer.strip()
                if not content:
                    return
                docs.append(
                    Document(
                        page_content=content,
                        metadata=self._build_metadata(
                            path=path,
                            filename=filename,
                            file_type="Word",
                            chunk_id=current_chunk_id,
                            chunk_index=chunk_index,
                            page_number=0,
                            content=content,
                        ),
                    )
                )
                overlap = self._overlap_text(content)
                chunk_index += 1
                current_chunk_id = new_chunk_id(chunk_index)
                buffer = overlap

            for child in list(body):
                if child.tag.endswith("}sectPr"):
                    continue

                text = self._paragraph_text(child)
                if text:
                    if buffer and not buffer.endswith(("\n", " ")):
                        buffer += "\n"
                    buffer += text

                for rel_id in self._image_rel_ids(child):
                    target = relationships.get(rel_id)
                    if not target:
                        continue
                    image_bytes, ext = self._read_docx_image(package, target)
                    record = self.image_store.save_image(
                        image_bytes=image_bytes,
                        ext=ext,
                        file_id=Path(filename).stem,
                        file_name=filename,
                        chunk_id=current_chunk_id,
                        page_number=0,
                        sort_order=len(extract_image_placeholders(buffer)),
                    )
                    if buffer and not buffer.endswith((" ", "\n")):
                        buffer += " "
                    buffer += record["placeholder"]

                if len(buffer) >= self.chunk_size:
                    seal()

            if buffer.strip():
                seal()
            return docs

    def _parse_pdf(self, path: Path, filename: str) -> list[Document]:
        try:
            import fitz
        except ImportError as exc:  # pragma: no cover - depends on optional runtime dependency
            raise RuntimeError("PDF 图文解析需要安装 PyMuPDF") from exc

        docs: list[Document] = []
        with fitz.open(path) as pdf:
            for page_index, page in enumerate(pdf):
                chunk_id = f"{filename}::image::{page_index}::0"
                parts: list[str] = []
                for block in sorted(page.get_text("dict").get("blocks", []), key=lambda b: (b.get("bbox", [0, 0])[1], b.get("bbox", [0, 0])[0])):
                    if block.get("type") == 0:
                        text = self._pdf_block_text(block)
                        if text:
                            parts.append(text)
                    elif block.get("type") == 1 and block.get("image"):
                        ext = block.get("ext") or "png"
                        record = self.image_store.save_image(
                            image_bytes=block["image"],
                            ext=ext,
                            file_id=Path(filename).stem,
                            file_name=filename,
                            chunk_id=chunk_id,
                            page_number=page_index,
                            sort_order=len([p for p in parts if p.startswith("<<IMAGE:")]),
                        )
                        parts.append(record["placeholder"])

                content = "\n".join(p for p in parts if p).strip()
                if not content:
                    continue
                docs.append(
                    Document(
                        page_content=content,
                        metadata=self._build_metadata(
                            path=path,
                            filename=filename,
                            file_type="PDF",
                            chunk_id=chunk_id,
                            chunk_index=len(docs),
                            page_number=page_index,
                            content=content,
                        ),
                    )
                )
        return docs

    @staticmethod
    def _read_docx_relationships(package: zipfile.ZipFile) -> dict[str, str]:
        try:
            rels_root = ET.fromstring(package.read("word/_rels/document.xml.rels"))
        except KeyError:
            return {}
        relationships: dict[str, str] = {}
        for rel in rels_root.findall("pkg_rel:Relationship", _NS):
            rel_id = rel.attrib.get("Id")
            target = rel.attrib.get("Target")
            rel_type = rel.attrib.get("Type", "")
            if rel_id and target and rel_type.endswith("/image"):
                relationships[rel_id] = target
        return relationships

    @staticmethod
    def _read_docx_image(package: zipfile.ZipFile, target: str) -> tuple[bytes, str]:
        normalized = posixpath.normpath(posixpath.join("word", target))
        image_bytes = package.read(normalized)
        return image_bytes, Path(normalized).suffix.lstrip(".") or "png"

    @staticmethod
    def _paragraph_text(element: ET.Element) -> str:
        parts = [node.text or "" for node in element.findall(".//w:t", _NS)]
        return "".join(parts).strip()

    @staticmethod
    def _image_rel_ids(element: ET.Element) -> list[str]:
        rel_ids: list[str] = []
        embed_key = f"{{{_NS['r']}}}embed"
        link_key = f"{{{_NS['r']}}}link"
        for blip in element.findall(".//a:blip", _NS):
            rel_id = blip.attrib.get(embed_key) or blip.attrib.get(link_key)
            if rel_id:
                rel_ids.append(rel_id)
        return rel_ids

    @staticmethod
    def _pdf_block_text(block: dict[str, Any]) -> str:
        lines: list[str] = []
        for line in block.get("lines", []):
            spans = [span.get("text", "") for span in line.get("spans", [])]
            text = "".join(spans).strip()
            if text:
                lines.append(text)
        return "\n".join(lines)

    def _overlap_text(self, content: str) -> str:
        clean = content.strip()
        if self.chunk_overlap <= 0 or len(clean) <= self.chunk_overlap:
            return ""
        return clean[-self.chunk_overlap:]

    @staticmethod
    def _build_metadata(
        path: Path,
        filename: str,
        file_type: str,
        chunk_id: str,
        chunk_index: int,
        page_number: int,
        content: str,
    ) -> dict[str, Any]:
        return {
            "_source": path.as_posix(),
            "_extension": path.suffix,
            "_file_name": filename,
            "filename": filename,
            "file_path": path.as_posix(),
            "file_type": file_type,
            "page_number": page_number,
            "chunk_id": chunk_id,
            "chunk_level": 3,
            "chunk_idx": chunk_index,
            "parent_chunk_id": "",
            "root_chunk_id": chunk_id,
            "image_placeholders": extract_image_placeholders(content),
        }


document_image_parser_service = DocumentImageParserService()
