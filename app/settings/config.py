"""应用配置模块。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict
import os

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=None, override=False):  # type: ignore[override]
        """
        Lightweight fallback loader so the app can run without python-dotenv.
        """
        if dotenv_path is None:
            return False

        path = Path(dotenv_path)
        if not path.exists():
            return False

        loaded = False
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = value
                loaded = True
        return loaded


load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_str(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass
class Settings:
    """应用配置。"""

    app_name: str = field(default_factory=lambda: _get_str("APP_NAME", "SuperBizAgent"))
    app_version: str = field(default_factory=lambda: _get_str("APP_VERSION", "1.0.0"))
    debug: bool = field(default_factory=lambda: _get_bool("DEBUG", False))
    host: str = field(default_factory=lambda: _get_str("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _get_int("PORT", 8800))

    dashscope_api_key: str = field(default_factory=lambda: _get_str("DASHSCOPE_API_KEY", ""))
    dashscope_api_base: str = field(
        default_factory=lambda: _get_str(
            "DASHSCOPE_API_BASE",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    )
    dashscope_model: str = field(
        default_factory=lambda: _get_str("DASHSCOPE_MODEL", "qwen3.5-flash")
    )
    dashscope_embedding_model: str = field(
        default_factory=lambda: _get_str("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v4")
    )
    embedding_dim: int = field(default_factory=lambda: _get_int("EMBEDDING_DIM", 1024))

    milvus_host: str = field(default_factory=lambda: _get_str("MILVUS_HOST", "localhost"))
    milvus_port: int = field(default_factory=lambda: _get_int("MILVUS_PORT", 19530))
    milvus_timeout: int = field(default_factory=lambda: _get_int("MILVUS_TIMEOUT", 10000))
    milvus_collection: str = field(
        default_factory=lambda: _get_str("MILVUS_COLLECTION", "mypaperweb_embeddings")
    )

    # ---- Elasticsearch：BM25 词法检索一路召回，与 Milvus 向量检索 RRF 融合 ----
    # ES 不可用时自动降级为纯 Milvus 检索，零影响
    es_retrieval_enabled: bool = field(default_factory=lambda: _get_bool("ES_RETRIEVAL_ENABLED", True))
    es_host: str = field(default_factory=lambda: _get_str("ES_HOST", "http://localhost:9200"))
    es_index: str = field(default_factory=lambda: _get_str("ES_INDEX", "mypaperweb_chunks"))

    rag_top_k: int = field(default_factory=lambda: _get_int("RAG_TOP_K", 3))
    rag_model: str = field(default_factory=lambda: _get_str("RAG_MODEL", "qwen3.5-flash"))

    chunk_max_size: int = field(default_factory=lambda: _get_int("CHUNK_MAX_SIZE", 800))
    chunk_overlap: int = field(default_factory=lambda: _get_int("CHUNK_OVERLAP", 100))
    chunk_size: int = field(default_factory=lambda: _get_int("CHUNK_SIZE", 1000))
    separators: list[str] = field(
        default_factory=lambda: ["\n\n", "\n", ".", "!", "?", "。", "？", "！", " ", ""]
    )
    max_split_char_number: int = field(
        default_factory=lambda: _get_int("MAX_SPLIT_CHAR_NUMBER", 1000)
    )
    similarity_threshold: int = field(default_factory=lambda: _get_int("SIMILARITY_THRESHOLD", 5))

    temp_file_max_count: int = field(default_factory=lambda: _get_int("TEMP_FILE_MAX_COUNT", 5))
    temp_file_max_size_mb: int = field(default_factory=lambda: _get_int("TEMP_FILE_MAX_SIZE_MB", 20))
    temp_file_max_total_size_mb: int = field(
        default_factory=lambda: _get_int("TEMP_FILE_MAX_TOTAL_SIZE_MB", 50)
    )
    temp_file_ttl_seconds: int = field(default_factory=lambda: _get_int("TEMP_FILE_TTL_SECONDS", 7200))

    web_search_key: str = field(default_factory=lambda: _get_str("WEB_SEARCH_KEY", ""))
    web_search_url: str = field(
        default_factory=lambda: _get_str("WEB_SEARCH_URL", "https://api.bocha.cn/v1/web-search")
    )
    tavily_api_key: str = field(default_factory=lambda: _get_str("TAVILY_API_KEY", ""))

    embedding_model_name: str = field(
        default_factory=lambda: _get_str("EMBEDDING_MODEL_NAME", "text-embedding-v4")
    )
    chat_model_name: str = field(
        default_factory=lambda: _get_str("CHAT_MODEL_NAME", "qwen3.5-flash")
    )

    summary_trigger: int = field(default_factory=lambda: _get_int("SUMMARY_TRIGGER", 10))
    summary_keep_last: int = field(default_factory=lambda: _get_int("SUMMARY_KEEP_LAST", 6))

    mcp_cls_transport: str = field(
        default_factory=lambda: _get_str("MCP_CLS_TRANSPORT", "streamable-http")
    )
    mcp_cls_url: str = field(
        default_factory=lambda: _get_str("MCP_CLS_URL", "http://localhost:8003/mcp")
    )
    mcp_monitor_transport: str = field(
        default_factory=lambda: _get_str("MCP_MONITOR_TRANSPORT", "streamable-http")
    )
    mcp_monitor_url: str = field(
        default_factory=lambda: _get_str("MCP_MONITOR_URL", "http://localhost:8004/mcp")
    )

    # ---- 多模态 RAG：视觉模型（论文图片 caption 生成）----
    # 缺省复用 DashScope 文本模型的 key/base，可通过环境变量单独覆盖
    vision_enabled: bool = field(default_factory=lambda: _get_bool("VISION_ENABLED", True))
    vision_model: str = field(default_factory=lambda: _get_str("VISION_MODEL", "qwen-vl-max"))
    vision_api_base: str = field(
        default_factory=lambda: _get_str("VISION_API_BASE", "")
    )
    vision_api_key: str = field(
        default_factory=lambda: _get_str("VISION_API_KEY", "")
    )
    # 索引时为图片生成 caption 失败是否阻断索引；False 时单图失败仅告警
    vision_strict: bool = field(default_factory=lambda: _get_bool("VISION_STRICT", False))

    # ---- 多模态 RAG 路线三：图像原生向量入索引（SOTA）----
    # 与 caption 双轨并存：caption 块写主 collection，图像向量写独立 image collection
    multimodal_embedding_enabled: bool = field(
        default_factory=lambda: _get_bool("MULTIMODAL_EMBEDDING_ENABLED", True)
    )
    multimodal_embedding_model: str = field(
        default_factory=lambda: _get_str("MULTIMODAL_EMBEDDING_MODEL", "multimodal-embedding-one-peace-v1")
    )
    multimodal_embedding_dim: int = field(
        default_factory=lambda: _get_int("MULTIMODAL_EMBEDDING_DIM", 1024)
    )
    # 图像向量独立 collection，零迁移风险；与主 collection 的 caption 块通过 chunk_id 关联
    milvus_image_collection: str = field(
        default_factory=lambda: _get_str("MILVUS_IMAGE_COLLECTION", "mypaperweb_image_embeddings")
    )

    # ---- Phase 6: 模型路由 + 语义缓存 + Langfuse 可观测 ----
    # 简单问题（实体问答/寒暄）路由到廉价模型，复杂问题走默认模型
    model_routing_enabled: bool = field(default_factory=lambda: _get_bool("MODEL_ROUTING_ENABLED", False))
    routing_simple_model: str = field(default_factory=lambda: _get_str("ROUTING_SIMPLE_MODEL", "qwen-turbo"))
    # Langfuse v2 自托管（llmops 栈提供），host 指向宿主机回环
    langfuse_enabled: bool = field(default_factory=lambda: _get_bool("LANGFUSE_ENABLED", True))
    langfuse_host: str = field(default_factory=lambda: _get_str("LANGFUSE_HOST", "http://host.docker.internal:3000"))
    # 语义缓存：仅 quick 问答路径，DashScope embedding + 余弦相似度
    semantic_cache_enabled: bool = field(default_factory=lambda: _get_bool("SEMANTIC_CACHE_ENABLED", False))
    semantic_cache_threshold: float = field(default_factory=lambda: _get_float("SEMANTIC_CACHE_THRESHOLD", 0.92))
    semantic_cache_ttl_hours: int = field(default_factory=lambda: _get_int("SEMANTIC_CACHE_TTL_HOURS", 72))
    semantic_cache_max_entries: int = field(default_factory=lambda: _get_int("SEMANTIC_CACHE_MAX_ENTRIES", 500))

    @property
    def DASHSCOPE_API_KEY(self) -> str:
        return self.dashscope_api_key

    @property
    def DASHSCOPE_API_BASE(self) -> str:
        return self.dashscope_api_base

    @property
    def EMBEDDING_DIM(self) -> int:
        return self.embedding_dim

    @property
    def MILVUS_HOST(self) -> str:
        return self.milvus_host

    @property
    def MILVUS_PORT(self) -> str:
        return str(self.milvus_port)

    @property
    def MILVUS_COLLECTION(self) -> str:
        return self.milvus_collection

    @property
    def ES_RETRIEVAL_ENABLED(self) -> bool:
        return self.es_retrieval_enabled

    @property
    def ES_HOST(self) -> str:
        return self.es_host

    @property
    def ES_INDEX(self) -> str:
        return self.es_index

    @property
    def WEB_SEARCH_KEY(self) -> str:
        return self.web_search_key

    @property
    def WEB_SEARCH_URL(self) -> str:
        return self.web_search_url

    @property
    def TAVILY_API_KEY(self) -> str:
        return self.tavily_api_key

    # ---- 多模态 RAG：视觉模型配置访问器（缺省回退 DashScope）----
    @property
    def VISION_ENABLED(self) -> bool:
        return self.vision_enabled

    @property
    def VISION_MODEL(self) -> str:
        return self.vision_model or "qwen-vl-max"

    @property
    def VISION_API_BASE(self) -> str:
        # 未单独配置则复用 DashScope 文本模型 base
        return self.vision_api_base or self.DASHSCOPE_API_BASE

    @property
    def VISION_API_KEY(self) -> str:
        # 未单独配置则复用 DashScope 文本模型 key
        return self.vision_api_key or self.DASHSCOPE_API_KEY

    @property
    def VISION_STRICT(self) -> bool:
        return self.vision_strict

    # ---- 多模态 embedding（路线三）配置访问器 ----
    @property
    def MULTIMODAL_EMBEDDING_ENABLED(self) -> bool:
        return self.multimodal_embedding_enabled

    @property
    def MULTIMODAL_EMBEDDING_MODEL(self) -> str:
        return self.multimodal_embedding_model or "multimodal-embedding-one-peace-v1"

    @property
    def MULTIMODAL_EMBEDDING_DIM(self) -> int:
        return self.multimodal_embedding_dim

    @property
    def MILVUS_IMAGE_COLLECTION(self) -> str:
        return self.milvus_image_collection

    @property
    def SUMMARY_TRIGGER(self) -> int:
        return self.summary_trigger

    @property
    def SUMMARY_KEEP_LAST(self) -> int:
        return self.summary_keep_last

    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        return {
            "cls": {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            },
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            },
        }


config = Settings()
