"""文档切分服务。"""

import os
from pathlib import Path
from typing import Dict, List

from langchain_community.document_loaders import (
    Docx2txtLoader,
    PyPDFLoader,
    UnstructuredExcelLoader,
)
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from loguru import logger

from settings.config import config

ALLOWED_EXTENSIONS = (".txt", ".text", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx")


class DocumentSplitterService:
    def __init__(self):
        self.chunk_size = config.chunk_max_size
        self.chunk_overlap = config.chunk_overlap

        level_1_size = max(2000, self.chunk_size * 2)
        level_1_overlap = max(240, self.chunk_overlap * 2)
        level_2_size = max(1000, self.chunk_size)
        level_2_overlap = max(120, self.chunk_overlap)
        level_3_size = max(500, self.chunk_size // 2)
        level_3_overlap = max(60, self.chunk_overlap // 2)
        separators = ["\n\n", "\n", "。", "！", "？", "；", ".", " ", ""]

        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2")],
            strip_headers=False,
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size * 2,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )
        self._splitter_level_1 = RecursiveCharacterTextSplitter(
            chunk_size=level_1_size,
            chunk_overlap=level_1_overlap,
            add_start_index=True,
            separators=separators,
        )
        self._splitter_level_2 = RecursiveCharacterTextSplitter(
            chunk_size=level_2_size,
            chunk_overlap=level_2_overlap,
            add_start_index=True,
            separators=separators,
        )
        self._splitter_level_3 = RecursiveCharacterTextSplitter(
            chunk_size=level_3_size,
            chunk_overlap=level_3_overlap,
            add_start_index=True,
            separators=separators,
        )
        logger.info("文档切分服务初始化完成")

    @staticmethod
    def _normalized_filename(file_path: str) -> str:
        result = Path(file_path).name if file_path else ""
        logger.info("文件名标准化完成: {}", result)
        return result

    @staticmethod
    def _build_chunk_id(filename: str, page_number: int, level: int, index: int) -> str:
        result = f"{filename}::p{page_number}::l{level}::{index}"
        logger.info("分块 ID 生成完成: {}", result)
        return result

    def _build_base_doc(
        self,
        file_path: str,
        file_type: str,
        page_number: int = 0,
        extra_metadata: Dict | None = None,
    ) -> Dict:
        normalized_path = Path(file_path).as_posix() if file_path else ""
        metadata = {
            "_source": normalized_path,
            "_extension": Path(file_path).suffix if file_path else "",
            "_file_name": self._normalized_filename(file_path),
            "filename": self._normalized_filename(file_path),
            "file_path": normalized_path,
            "file_type": file_type,
            "page_number": page_number,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        logger.info("基础元数据构建完成: {}", metadata.get("filename", ""))
        return metadata

    def split_three_levels(
        self,
        text: str,
        base_doc: Dict,
        page_global_chunk_idx: int,
    ) -> List[Document]:
        try:
            if not text:
                #logger.info("三级切分完成，输入为空")
                return []

            root_chunks: List[Document] = []
            page_number = int(base_doc.get("page_number", 0))
            filename = str(base_doc.get("filename", ""))
            level_1_docs = self._splitter_level_1.create_documents([text], [base_doc])
            level_1_counter = 0
            level_2_counter = 0
            level_3_counter = 0

            for level_1_doc in level_1_docs:
                level_1_text = (level_1_doc.page_content or "").strip()
                if not level_1_text:
                    continue

                level_1_id = self._build_chunk_id(filename, page_number, 1, level_1_counter)
                level_1_counter += 1
                root_chunks.append(
                    Document(
                        page_content=level_1_text,
                        metadata={
                            **base_doc,
                            "chunk_id": level_1_id,
                            "chunk_level": 1,
                            "chunk_idx": page_global_chunk_idx,
                            "parent_chunk_id": "",
                            "root_chunk_id": level_1_id,
                        },
                    )
                )
                page_global_chunk_idx += 1

                level_2_docs = self._splitter_level_2.create_documents([level_1_text], [base_doc])
                for level_2_doc in level_2_docs:
                    level_2_text = (level_2_doc.page_content or "").strip()
                    if not level_2_text:
                        continue

                    level_2_id = self._build_chunk_id(filename, page_number, 2, level_2_counter)
                    level_2_counter += 1
                    root_chunks.append(
                        Document(
                            page_content=level_2_text,
                            metadata={
                                **base_doc,
                                "chunk_id": level_2_id,
                                "chunk_level": 2,
                                "chunk_idx": page_global_chunk_idx,
                                "parent_chunk_id": level_1_id,
                                "root_chunk_id": level_1_id,
                            },
                        )
                    )
                    page_global_chunk_idx += 1

                    level_3_docs = self._splitter_level_3.create_documents([level_2_text], [base_doc])
                    for level_3_doc in level_3_docs:
                        level_3_text = (level_3_doc.page_content or "").strip()
                        if not level_3_text:
                            continue

                        level_3_id = self._build_chunk_id(filename, page_number, 3, level_3_counter)
                        level_3_counter += 1
                        root_chunks.append(
                            Document(
                                page_content=level_3_text,
                                metadata={
                                    **base_doc,
                                    "chunk_id": level_3_id,
                                    "chunk_level": 3,
                                    "chunk_idx": page_global_chunk_idx,
                                    "parent_chunk_id": level_2_id,
                                    "root_chunk_id": level_1_id,
                                },
                            )
                        )
                        page_global_chunk_idx += 1

            logger.info("三级切分完成，生成 {} 个分块", len(root_chunks))
            return root_chunks
        except Exception as exc:
            logger.error("三级切分失败: {}", exc)
            raise

    def load_document(self, file_path: str, filename: str) -> List[Document]:
        file_lower = filename.lower()
        normalized_path = Path(file_path).as_posix()

        try:
            if file_lower.endswith(".pdf"):
                doc_type = "PDF"
                raw_docs = PyPDFLoader(normalized_path).load()
            elif file_lower.endswith((".docx", ".doc")):
                doc_type = "Word"
                raw_docs = Docx2txtLoader(normalized_path).load()
            elif file_lower.endswith((".xlsx", ".xls")):
                doc_type = "Excel"
                raw_docs = UnstructuredExcelLoader(normalized_path).load()
            elif file_lower.endswith(".md"):
                content = Path(normalized_path).read_text(encoding="utf-8")
                result = self.split_markdown(content, normalized_path)
                logger.info("文档加载完成: {}", normalized_path)
                return result
            elif file_lower.endswith((".txt", ".text")):
                content = Path(normalized_path).read_text(encoding="utf-8")
                result = self.split_text(content, normalized_path)
                logger.info("文档加载完成: {}", normalized_path)
                return result
            else:
                raise ValueError(f"不支持的文件类型: {file_path}")
        except Exception as exc:
            logger.error("文档加载失败: {}，错误: {}", file_path, exc)
            raise Exception(f"出现问题的文件: {file_path}") from exc

        try:
            documents: List[Document] = []
            page_global_chunk_idx = 0
            for doc in raw_docs:
                base_doc = self._build_base_doc(
                    normalized_path,
                    doc_type,
                    page_number=int((doc.metadata or {}).get("page", 0) or 0),
                )
                page_chunks = self.split_three_levels(
                    text=(doc.page_content or "").strip(),
                    base_doc=base_doc,
                    page_global_chunk_idx=page_global_chunk_idx,
                )
                page_global_chunk_idx += len(page_chunks)
                documents.extend(page_chunks)
            logger.info("文档处理完成: {}，分块数: {}", file_path, len(documents))
            return documents
        except Exception as exc:
            logger.error("文档处理失败: {}，错误: {}", file_path, exc)
            raise Exception(f"处理文档失败: {exc}") from exc

    def load_documents_from_folder(self, folder_path: str) -> List[Document]:
        try:
            all_documents: List[Document] = []
            for filename in os.listdir(folder_path):
                file_path = os.path.join(folder_path, filename)
                if not file_path.lower().endswith(ALLOWED_EXTENSIONS):
                    logger.warning("跳过不支持的文件: {}", filename)
                    continue
                try:
                    all_documents.extend(self.load_document(file_path, filename))
                except Exception as exc:
                    logger.error("处理文件失败，已跳过: {}，错误: {}", file_path, exc)
            logger.info("文件夹加载完成，总分块数: {}", len(all_documents))
            return all_documents
        except Exception as exc:
            logger.error("文件夹加载失败: {}", exc)
            raise

    def split_markdown(self, content: str, file_path: str = "") -> List[Document]:
        try:
            if not content or not content.strip():
                logger.info("Markdown 切分完成，输入为空")
                return []

            md_docs = self.markdown_splitter.split_text(content)
            final_docs: List[Document] = []
            page_global_chunk_idx = 0
            for md_doc in md_docs:
                base_doc = self._build_base_doc(
                    file_path,
                    "Markdown",
                    page_number=0,
                    extra_metadata=md_doc.metadata,
                )
                sub_docs = self.split_three_levels(md_doc.page_content, base_doc, page_global_chunk_idx)
                page_global_chunk_idx += len(sub_docs)
                final_docs.extend(sub_docs)

            logger.info("Markdown 切分完成，生成 {} 个分块", len(final_docs))
            return final_docs
        except Exception as exc:
            logger.error("Markdown 切分失败: {}", exc)
            raise

    def split_text(self, content: str, file_path: str = "") -> List[Document]:
        try:
            if not content or not content.strip():
                logger.info("文本切分完成，输入为空")
                return []

            base_doc = self._build_base_doc(file_path, "Text", page_number=0)
            documents = self.split_three_levels(
                text=content.strip(),
                base_doc=base_doc,
                page_global_chunk_idx=0,
            )
            logger.info("文本切分完成，生成 {} 个分块", len(documents))
            return documents
        except Exception as exc:
            logger.error("文本切分失败: {}", exc)
            raise Exception(f"处理文档失败: {exc}") from exc

    def split_document(self, file_path: str = "") -> List[Document]:
        try:
            if file_path.lower().endswith(ALLOWED_EXTENSIONS):
                result = self.load_document(file_path, Path(file_path).name)
                logger.info("智能切分完成: {}", file_path)
                return result
            raise Exception(f"不支持的文件类型: {file_path}")
        except Exception as exc:
            logger.error("智能切分失败: {}", exc)
            raise

    def _merge_small_chunks(self, documents: List[Document], min_size: int = 300) -> List[Document]:
        try:
            if not documents:
                logger.info("小分块合并完成，输入为空")
                return []

            merged_docs: List[Document] = []
            current_doc: Document | None = None
            for doc in documents:
                doc_size = len(doc.page_content)
                if current_doc is None:
                    current_doc = doc
                elif doc_size < min_size and len(current_doc.page_content) < self.chunk_size * 2:
                    current_doc.page_content += "\n\n" + doc.page_content
                else:
                    merged_docs.append(current_doc)
                    current_doc = doc

            if current_doc is not None:
                merged_docs.append(current_doc)

            logger.info("小分块合并完成，输出 {} 个分块", len(merged_docs))
            return merged_docs
        except Exception as exc:
            logger.error("小分块合并失败: {}", exc)
            raise


document_splitter_service = DocumentSplitterService()
