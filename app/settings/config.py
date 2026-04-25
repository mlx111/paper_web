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
    def WEB_SEARCH_KEY(self) -> str:
        return self.web_search_key

    @property
    def WEB_SEARCH_URL(self) -> str:
        return self.web_search_url

    @property
    def TAVILY_API_KEY(self) -> str:
        return self.tavily_api_key

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
