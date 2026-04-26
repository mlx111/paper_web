"""Vector indexing service."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from services.document_splitter_service import document_splitter_service
from services.chunk_image_store_service import extract_image_placeholders
from services.document_image_parser_service import document_image_parser_service
from services.index_manifest_service import index_manifest_service
from services.mlivus_server_service import mlivus_server_service
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
                    return image_docs
                logger.info("图文解析未发现图片，回退普通解析: {}", normalized_path)
            except Exception as exc:
                logger.warning("图文解析失败，回退普通解析: {}，错误: {}", normalized_path, exc)

        return document_splitter_service.split_document(normalized_path)

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
