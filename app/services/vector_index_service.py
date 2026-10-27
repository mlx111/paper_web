"""Vector indexing service."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

try:
    from langchain_core.documents import Document
except Exception:  # pragma: no cover - 兼容轻量测试环境
    class Document:  # type: ignore[no-redef]
        def __init__(self, page_content: str, metadata: dict | None = None):
            self.page_content = page_content
            self.metadata = metadata or {}

from settings.config import config
from services.document_splitter_service import document_splitter_service
from services.chunk_image_store_service import (
    default_chunk_image_store,
    extract_image_placeholders,
)
from services.document_image_parser_service import document_image_parser_service
from services.image_caption_service import image_caption_service
from services.index_manifest_service import index_manifest_service
from services.mlivus_client_service import mlivus_client_service
from services.mlivus_server_service import mlivus_server_service
from services.multimodal_embedding_service import multimodal_embedding_service
from services.parent_chunk_service import parent_chunk_store


class IndexingResult:
    def __init__(self):
        self.success = False
        self.directory_path = ""
        self.total_files = 0
        self.success_count = 0
        self.fail_count = 0
        self.skipped_count = 0
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.error_message = ""
        self.failed_files: Dict[str, str] = {}

    def increment_success_count(self):
        self.success_count += 1

    def increment_fail_count(self):
        self.fail_count += 1

    def increment_skipped_count(self):
        self.skipped_count += 1

    def add_failed_file(self, file_path: str, error: str):
        self.failed_files[file_path] = error

    def get_duration_ms(self) -> int:
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time).total_seconds() * 1000)
        return 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "directory_path": self.directory_path,
            "total_files": self.total_files,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "skipped_count": self.skipped_count,
            "duration_ms": self.get_duration_ms(),
            "error_message": self.error_message,
            "failed_files": self.failed_files,
        }


class VectorIndexService:
    def __init__(self):
        self.project_root = Path(__file__).resolve().parents[2]
        self.upload_path = self.project_root / "uploads"
        self.supported_extensions = (".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx")
        logger.info("向量索引服务初始化完成")

    def _collect_files(self, dir_path: Path) -> list[Path]:
        files: list[Path] = []
        for ext in self.supported_extensions:
            files.extend(dir_path.glob(f"*{ext}"))
        return sorted(files)

    def _ensure_directory(self, dir_path: Path) -> Path:
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def _file_state(self, path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns

    def _split_file_for_index(self, normalized_path: str):
        path = Path(normalized_path)
        if path.suffix.lower() in {".pdf", ".docx"}:
            try:
                image_docs = document_image_parser_service.parse(normalized_path, path.name)
                has_images = any(
                    extract_image_placeholders(doc.page_content or "")
                    for doc in image_docs
                )
                if has_images:
                    logger.info(
                        "图文解析命中图片，占位符分块数: {}，文件: {}",
                        len(image_docs),
                        normalized_path,
                    )
                    # 多模态 RAG：为每张图生成 caption 并追加独立图片块
                    self._augment_with_image_chunks(image_docs, path)
                    return image_docs
                logger.info("图文解析未发现图片，回退普通解析: {}", normalized_path)
            except Exception as exc:
                logger.warning("图文解析失败，回退普通解析: {}，错误: {}", normalized_path, exc)

        return document_splitter_service.split_document(normalized_path)

    def _augment_with_image_chunks(self, image_docs: list[Document], path: Path) -> None:
        """对已解析的图文分块，遍历其中的图片占位符双轨写入：

        路线一（caption 块）：qwen-vl-max 生成中文 caption → 独立图片块写入主 collection
        路线三（图像向量）：multimodal-embedding 生成图像原生向量 → 写入 image collection

        双轨互不依赖：caption 失败仍可写 image 向量，image 向量失败仍可写 caption 块。
        仅当两者都失败时跳过该图。原始块保留 `<<IMAGE:xxxx>>` 占位符。
        """
        if not image_docs:
            return

        # 收集本文件所有占位符（保持出现顺序）
        seen_placeholders: list[str] = []
        seen_set: set[str] = set()
        for doc in image_docs:
            for ph in extract_image_placeholders(doc.page_content or ""):
                if ph not in seen_set:
                    seen_set.add(ph)
                    seen_placeholders.append(ph)

        if not seen_placeholders:
            return

        logger.info(
            "为 {} 张图片生成 caption + 图像向量，文件: {}",
            len(seen_placeholders),
            path.name,
        )

        # 确保 image collection 存在（路线三独立 collection，零迁移风险）
        if multimodal_embedding_service.enabled:
            try:
                mlivus_client_service.init_image_collection()
            except Exception as exc:
                logger.warning("image collection 初始化失败，路线三降级为单轨: {}", exc)

        filename = path.name
        file_type = "PDF" if path.suffix.lower() == ".pdf" else "Word"

        # 用最后一页 page_number 作为图片块的页码基线（避免误读为 page=0）
        last_page_number = 0
        for doc in image_docs:
            page = int((doc.metadata or {}).get("page_number", 0) or 0)
            if page > last_page_number:
                last_page_number = page

        strict = config.VISION_STRICT
        chunk_idx_base = len(image_docs)
        caption_appended = 0
        image_vec_appended = 0

        for idx, placeholder in enumerate(seen_placeholders):
            # ① 路线一：生成 caption
            try:
                caption = image_caption_service.caption_placeholder(placeholder)
            except Exception as exc:
                logger.warning("生成 caption 异常: {}，错误: {}", placeholder, exc)
                caption = ""

            # ② 路线三：生成图像向量
            image_vec: list[float] = []
            if multimodal_embedding_service.enabled:
                try:
                    image_record = default_chunk_image_store.get_image_record(placeholder) or {}
                    image_path_str = image_record.get("image_path") or ""
                    if image_path_str and Path(image_path_str).exists():
                        img_path = Path(image_path_str)
                        ext = img_path.suffix.lstrip(".").lower() or "png"
                        image_bytes = img_path.read_bytes()
                        image_vec = multimodal_embedding_service.embed_image(image_bytes, ext)
                    else:
                        logger.warning("未找到图片文件，跳过图像向量: {}", placeholder)
                except Exception as exc:
                    logger.warning("生成图像向量异常: {}，错误: {}", placeholder, exc)
                    image_vec = []

            # ③ 双轨互不依赖：两者都失败才跳过
            if not caption and not image_vec:
                if strict:
                    raise RuntimeError(
                        f"图片 caption 和图像向量均失败: {placeholder}"
                    )
                logger.warning("caption 和图像向量均失败，跳过: {}", placeholder)
                continue

            image_id = placeholder.strip("<>").replace("IMAGE:", "").strip()
            chunk_id = f"{filename}::image_caption::{image_id}"

            # 路线一：写主 collection caption 块
            if caption:
                page_content = f"{placeholder}\n图片说明：{caption}"
                image_record = default_chunk_image_store.get_image_record(placeholder) or {}
                metadata = {
                    "_source": path.as_posix(),
                    "_extension": path.suffix,
                    "_file_name": filename,
                    "filename": filename,
                    "file_path": path.as_posix(),
                    "file_type": file_type,
                    "page_number": int(image_record.get("page_number") or last_page_number),
                    "chunk_id": chunk_id,
                    "chunk_level": 3,  # 叶子层，与原文档一致，可被默认 hybrid_retrieve 命中
                    "chunk_idx": chunk_idx_base + idx,
                    "parent_chunk_id": "",
                    "root_chunk_id": chunk_id,
                    "image_placeholders": [placeholder],
                    "chunk_type": "image",
                }
                image_docs.append(
                    Document(page_content=page_content, metadata=metadata)
                )
                caption_appended += 1

            # 路线三：写 image collection 图像向量
            if image_vec:
                image_record = default_chunk_image_store.get_image_record(placeholder) or {}
                try:
                    mlivus_client_service.insert_image([{
                        "image_dense_embedding": image_vec,
                        "chunk_id": chunk_id,  # 关联主 collection 的 caption 块
                        "image_placeholder": placeholder,
                        "image_url": f"/file/image/{image_id}",
                        "caption": caption or "",
                        "source_file": path.as_posix(),
                        "page_number": int(image_record.get("page_number") or last_page_number),
                        "file_id": filename,
                    }])
                    image_vec_appended += 1
                    logger.info("图像向量写入成功: {}", placeholder)
                except Exception as exc:
                    logger.warning("图像向量写入失败（caption 块仍可用）: {}，错误: {}", placeholder, exc)

        logger.info(
            "图片双轨写入完成: caption 块 {}/{}，图像向量 {}/{}，文件: {}",
            caption_appended,
            len(seen_placeholders),
            image_vec_appended,
            len(seen_placeholders),
            filename,
        )

    def index_directory(self, directory_path: Optional[str] = None) -> IndexingResult:
        result = IndexingResult()
        result.start_time = datetime.now()

        try:
            target_path = Path(directory_path).resolve() if directory_path else self.upload_path.resolve()
            dir_path = target_path

            if not dir_path.exists() or not dir_path.is_dir():
                raise ValueError(f"目录不存在或不是有效目录: {target_path}")

            result.directory_path = str(dir_path)
            files = (
                list(dir_path.glob("*.txt"))
                + list(dir_path.glob("*.md"))
                + list(dir_path.glob("*.pdf"))
                + list(dir_path.glob("*.doc"))
                + list(dir_path.glob("*.docx"))
                + list(dir_path.glob("*.xls"))
                + list(dir_path.glob("*.xlsx"))
            )

            if not files:
                logger.warning("目录中没有找到支持的文件: {}", target_path)
                result.total_files = 0
                result.success = True
                result.end_time = datetime.now()
                return result

            result.total_files = len(files)
            logger.info("开始索引目录 {}, 找到 {} 个文件", target_path, len(files))

            for file_path in files:
                try:
                    self.index_single_file(str(file_path))
                    result.increment_success_count()
                    logger.info("文件索引成功: {}", file_path.name)
                except Exception as exc:
                    result.increment_fail_count()
                    result.add_failed_file(str(file_path), str(exc))
                    logger.error("文件索引失败: {}, 错误: {}", file_path.name, exc)

            result.success = result.fail_count == 0
            result.end_time = datetime.now()
            logger.info(
                "目录索引完成: 总数={}, 成功={}, 失败={}",
                result.total_files,
                result.success_count,
                result.fail_count,
            )
            return result
        except Exception as exc:
            logger.error("索引目录失败: {}", exc)
            result.success = False
            result.error_message = str(exc)
            result.end_time = datetime.now()
            return result

    def sync_directory_incrementally(self, directory_path: Optional[str] = None) -> IndexingResult:
        result = IndexingResult()
        result.start_time = datetime.now()

        try:
            target_path = Path(directory_path).resolve() if directory_path else self.upload_path.resolve()
            dir_path = target_path

            if not dir_path.exists():
                if directory_path is None:
                    dir_path = self._ensure_directory(dir_path)
                else:
                    raise ValueError(f"目录不存在或不是有效目录: {target_path}")

            if not dir_path.is_dir():
                raise ValueError(f"目录不存在或不是有效目录: {target_path}")

            result.directory_path = str(dir_path)
            files = self._collect_files(dir_path)

            if not files:
                logger.info("增量同步时未发现可索引文件: {}", target_path)
                result.total_files = 0
                result.success = True
                result.end_time = datetime.now()
                return result

            result.total_files = len(files)
            logger.info("开始增量校验目录 {}, 找到 {} 个文件", target_path, len(files))

            for file_path in files:
                try:
                    size, mtime_ns = self._file_state(file_path)
                    if index_manifest_service.is_unchanged(file_path, size=size, mtime_ns=mtime_ns):
                        result.increment_skipped_count()
                        logger.info("文件未变化，跳过索引: {}", file_path.name)
                        continue

                    self.index_single_file(str(file_path))
                    result.increment_success_count()
                    logger.info("文件增量索引成功: {}", file_path.name)
                except Exception as exc:
                    result.increment_fail_count()
                    result.add_failed_file(str(file_path), str(exc))
                    logger.error("文件增量索引失败: {}, 错误: {}", file_path.name, exc)

            result.success = result.fail_count == 0
            result.end_time = datetime.now()
            logger.info(
                "增量同步完成: 总数={}, 成功={}, 失败={}, 跳过={}",
                result.total_files,
                result.success_count,
                result.fail_count,
                result.skipped_count,
            )
            return result
        except Exception as exc:
            logger.error("增量同步目录失败: {}", exc)
            result.success = False
            result.error_message = str(exc)
            result.end_time = datetime.now()
            return result

    def index_single_file(self, file_path: str):
        path = Path(file_path).resolve()
        if not path.exists() or not path.is_file():
            raise ValueError(f"文件不存在: {file_path}")

        logger.info("开始索引文件: {}", path)
        try:
            normalized_path = path.as_posix()
            documents = self._split_file_for_index(normalized_path)
            logger.info("文档切分完成: {} -> {} 个分片", file_path, len(documents))

            if documents:
                parent_docs = [
                    doc for doc in documents if int((doc.metadata or {}).get("chunk_level", 0) or 0) < 3
                ]
                mlivus_server_service.delete_by_source(normalized_path)
                parent_chunk_store.delete_by_source(normalized_path)
                # 路线三：清理 image collection 旧数据（容错：collection 不存在时跳过）
                try:
                    mlivus_client_service.delete_image_by_source(normalized_path)
                except Exception as exc:
                    logger.warning("清理 image collection 旧数据失败（可忽略）: {}", exc)
                if parent_docs:
                    parent_chunk_store.upsert_documents(parent_docs)
                mlivus_server_service.write_documents(documents)
                logger.info("文件索引完成: {}, 共 {} 个分片", file_path, len(documents))
            else:
                logger.warning("文件内容为空或无法分片: {}", file_path)

            size, mtime_ns = self._file_state(path)
            index_manifest_service.mark_indexed(path, size=size, mtime_ns=mtime_ns)
        except Exception as exc:
            logger.error("索引文件失败: {}, 错误: {}", file_path, exc)
            raise RuntimeError(f"索引文件失败: {exc}") from exc


vector_index_service = VectorIndexService()
