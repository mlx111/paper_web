"""Embedding 模型配置服务：文本 embedding + 多模态 embedding 的运行时可配置化。

设计要点（与 llm_config_service 一致的工程约束）：
- 配置持久化到 app/data/embedding_config.json（docker volume 挂载，重启不丢、不进镜像/不提交 git）。
- API Key 用 Fernet 对称加密后落盘；复用 llm_config_service 的同一 secret（app/data/.llm_secret），
  GET 接口只回「是否已配置 + 掩码」，绝不返回明文；PUT 时 api_key 留空表示不修改。
- 配置更改立即生效（lazy 读取，不在 __init__ 缓存）——embodeding_service / image_caption_service /
  multimodal_embedding_service 用 property 每次读取当前激活值，无需重启容器。
- 维度变更会破坏既有 Milvus collection（向量维度不可变），update_config 默认拒绝写入并提示
  需要重建 collection；force_reindex=True 时允许（Phase 2 前端二次确认后调用）。
- 预设表：DashScope text-embedding-v4（1024 维）/ DashScope multimodal-embedding-one-peace-v1
  （1024 维，原生 API）/ OpenAI / Ollama / 自定义。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from settings.config import config

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_CONFIG_PATH = _DATA_DIR / "embedding_config.json"
_SECRET_PATH = _DATA_DIR / ".llm_secret"


# 文本 embedding 供应商预设：id / 显示名 / 默认 base_url / 默认模型 / 默认维度 / 是否需要 API Key
TEXT_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "dashscope",
        "name": "阿里云百炼 DashScope (text-embedding-v4)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "text-embedding-v4",
        "default_dim": 1024,
        "requires_api_key": True,
    },
    {
        "id": "openai",
        "name": "OpenAI text-embedding-3-small",
        "base_url": "https://api.openai.com/v1",
        "default_model": "text-embedding-3-small",
        "default_dim": 1536,
        "requires_api_key": True,
    },
    {
        "id": "ollama",
        "name": "Ollama 本地 embedding（如 bge-m3）",
        "base_url": "http://host.docker.internal:11434/v1",
        "default_model": "bge-m3:latest",
        "default_dim": 1024,
        "requires_api_key": False,
    },
    {
        "id": "custom",
        "name": "自定义（OpenAI 兼容 /v1/embeddings）",
        "base_url": "",
        "default_model": "",
        "default_dim": 1024,
        "requires_api_key": True,
    },
]

# 多模态 embedding 供应商预设：多模态 embedding 多为厂商原生 API，不兼容 OpenAI 协议
MULTIMODAL_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "dashscope",
        "name": "阿里云百炼 DashScope (multimodal-embedding-one-peace-v1)",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "default_model": "multimodal-embedding-one-peace-v1",
        "default_dim": 1024,
        "requires_api_key": True,
    },
    {
        "id": "custom",
        "name": "自定义（原生多模态 API）",
        "base_url": "",
        "default_model": "",
        "default_dim": 1024,
        "requires_api_key": True,
    },
]

_TEXT_PROVIDER_MAP = {p["id"]: p for p in TEXT_PROVIDERS}
_MM_PROVIDER_MAP = {p["id"]: p for p in MULTIMODAL_PROVIDERS}


class EmbeddingConfigService:
    """读写文本 / 多模态 embedding 配置，并对外提供明文参数。"""

    def __init__(self) -> None:
        self._cache: dict[str, Any] | None = None

    # ---------- 加密（复用 llm_config_service 的同一 Fernet secret）----------
    def _fernet(self):
        from cryptography.fernet import Fernet

        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        if _SECRET_PATH.exists():
            key = _SECRET_PATH.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            _SECRET_PATH.write_bytes(key)
            try:
                _SECRET_PATH.chmod(0o600)
            except OSError:
                pass
        return Fernet(key)

    def _encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        return self._fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _decrypt(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._fernet().decrypt(token.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            logger.warning("Embedding API Key 解密失败：{}", exc)
            return ""

    # ---------- 加载 / 保存 ----------
    def _default_config(self) -> dict[str, Any]:
        """首次启动：用 .env 里的 DashScope 配置初始化（文本 + 多模态）。"""
        text_dashscope = {
            "model": config.dashscope_embedding_model or "text-embedding-v4",
            "base_url": config.DASHSCOPE_API_BASE
            or _TEXT_PROVIDER_MAP["dashscope"]["base_url"],
            "api_key_enc": self._encrypt(config.DASHSCOPE_API_KEY or ""),
            "dim": config.embedding_dim or 1024,
        }
        mm_dashscope = {
            "model": config.MULTIMODAL_EMBEDDING_MODEL,
            "base_url": _MM_PROVIDER_MAP["dashscope"]["base_url"],
            "api_key_enc": self._encrypt(config.DASHSCOPE_API_KEY or ""),
            "dim": config.MULTIMODAL_EMBEDDING_DIM,
        }
        return {
            "text": {
                "active_provider": "dashscope",
                "providers": {"dashscope": text_dashscope},
            },
            "multimodal": {
                "active_provider": "dashscope",
                "enabled": config.MULTIMODAL_EMBEDDING_ENABLED,
                "providers": {"dashscope": mm_dashscope},
            },
            "updated_at": time.time(),
        }

    def _load(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if _CONFIG_PATH.exists():
            try:
                data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
                self._cache = data
                return self._cache
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Embedding 配置文件读取失败，回退默认：{}", exc)
        self._cache = self._default_config()
        self._persist(self._cache)
        return self._cache

    def _persist(self, data: dict[str, Any]) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_PATH)

    # ---------- 对外：文本 embedding 明文参数 ----------
    def get_text_params(self) -> dict[str, Any]:
        """返回当前激活文本 embedding 的明文字段（供 embodeding_service 实例化用）。"""
        cfg = self._load()
        text_cfg = cfg.get("text", {})
        provider_id = text_cfg.get("active_provider") or "dashscope"
        preset = _TEXT_PROVIDER_MAP.get(provider_id, _TEXT_PROVIDER_MAP["custom"])
        entry = text_cfg.get("providers", {}).get(provider_id, {})
        return {
            "provider": provider_id,
            "model": entry.get("model") or preset["default_model"],
            "base_url": entry.get("base_url") or preset["base_url"],
            "api_key": self._decrypt(entry.get("api_key_enc") or ""),
            "dim": int(entry.get("dim") or preset["default_dim"]),
        }

    # ---------- 对外：多模态 embedding 明文参数 ----------
    def get_multimodal_params(self) -> dict[str, Any]:
        """返回当前激活多模态 embedding 的明文字段（供 multimodal_embedding_service 用）。"""
        cfg = self._load()
        mm_cfg = cfg.get("multimodal", {})
        provider_id = mm_cfg.get("active_provider") or "dashscope"
        preset = _MM_PROVIDER_MAP.get(provider_id, _MM_PROVIDER_MAP["custom"])
        entry = mm_cfg.get("providers", {}).get(provider_id, {})
        return {
            "provider": provider_id,
            "enabled": bool(mm_cfg.get("enabled", True)),
            "model": entry.get("model") or preset["default_model"],
            "base_url": entry.get("base_url") or preset["base_url"],
            "api_key": self._decrypt(entry.get("api_key_enc") or ""),
            "dim": int(entry.get("dim") or preset["default_dim"]),
        }

    # ---------- 对外：页面用的脱敏配置 ----------
    @staticmethod
    def _mask(key: str) -> str:
        if not key:
            return ""
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"

    def get_public_config(self) -> dict[str, Any]:
        cfg = self._load()
        text_active = self.get_text_params()
        mm_active = self.get_multimodal_params()

        text_provider_configs: dict[str, Any] = {}
        for pid, entry in cfg.get("text", {}).get("providers", {}).items():
            key = self._decrypt(entry.get("api_key_enc") or "")
            text_provider_configs[pid] = {
                "model": entry.get("model") or "",
                "base_url": entry.get("base_url") or "",
                "dim": int(entry.get("dim") or 1024),
                "has_api_key": bool(key),
                "api_key_masked": self._mask(key),
            }

        mm_provider_configs: dict[str, Any] = {}
        for pid, entry in cfg.get("multimodal", {}).get("providers", {}).items():
            key = self._decrypt(entry.get("api_key_enc") or "")
            mm_provider_configs[pid] = {
                "model": entry.get("model") or "",
                "base_url": entry.get("base_url") or "",
                "dim": int(entry.get("dim") or 1024),
                "has_api_key": bool(key),
                "api_key_masked": self._mask(key),
            }

        return {
            "text": {
                "provider": text_active["provider"],
                "model": text_active["model"],
                "base_url": text_active["base_url"],
                "dim": text_active["dim"],
                "has_api_key": bool(text_active["api_key"]),
                "api_key_masked": self._mask(text_active["api_key"]),
                "provider_configs": text_provider_configs,
                "providers": [
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "base_url": p["base_url"],
                        "default_model": p["default_model"],
                        "default_dim": p["default_dim"],
                        "requires_api_key": p["requires_api_key"],
                    }
                    for p in TEXT_PROVIDERS
                ],
            },
            "multimodal": {
                "provider": mm_active["provider"],
                "enabled": mm_active["enabled"],
                "model": mm_active["model"],
                "base_url": mm_active["base_url"],
                "dim": mm_active["dim"],
                "has_api_key": bool(mm_active["api_key"]),
                "api_key_masked": self._mask(mm_active["api_key"]),
                "provider_configs": mm_provider_configs,
                "providers": [
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "base_url": p["base_url"],
                        "default_model": p["default_model"],
                        "default_dim": p["default_dim"],
                        "requires_api_key": p["requires_api_key"],
                    }
                    for p in MULTIMODAL_PROVIDERS
                ],
            },
        }

    # ---------- 对外：更新配置（维度变化需重建索引）----------
    def update_config(
        self,
        scope: str,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        dim: int | None = None,
        enabled: bool | None = None,
        force_reindex: bool = False,
    ) -> dict[str, Any]:
        """保存指定 scope（text / multimodal）的配置。

        维度变化会破坏既有 Milvus collection（向量维度不可变），默认拒绝写入并返回错误；
        force_reindex=True 时允许（Phase 2 前端二次确认后调用）。
        api_key 留空表示不修改该供应商已保存的 Key。
        """
        if scope not in {"text", "multimodal"}:
            return {"ok": False, "message": f"未知 scope: {scope}"}

        cfg = self._load()
        scope_cfg = cfg.setdefault(scope, {})
        provider_id = (provider or scope_cfg.get("active_provider") or "dashscope").strip()
        preset_map = _TEXT_PROVIDER_MAP if scope == "text" else _MM_PROVIDER_MAP
        preset = preset_map.get(provider_id, preset_map["custom"])
        entry = dict(scope_cfg.get("providers", {}).get(provider_id, {}))

        # 维度校验：变化时默认拒绝，要求确认重建索引
        current_dim = int(entry.get("dim") or preset["default_dim"])
        new_dim = int(dim) if dim is not None else current_dim
        if new_dim != current_dim and not force_reindex:
            return {
                "ok": False,
                "message": (
                    f"维度从 {current_dim} 变为 {new_dim}，会导致既有 Milvus collection "
                    f"向量维度不匹配。请先清空对应 collection 再重新索引，"
                    f"或在确认无数据损失的情况下使用 force_reindex=True。"
                ),
                "requires_reindex": True,
            }
        if new_dim != current_dim:
            logger.warning(
                "Embedding {} 维度强制变更: {} -> {}（force_reindex=True）",
                scope,
                current_dim,
                new_dim,
            )

        # api_key：留空表示不修改，保留该供应商原密钥
        if api_key and api_key.strip():
            entry["api_key_enc"] = self._encrypt(api_key.strip())

        entry["model"] = (model or "").strip() or entry.get("model") or preset["default_model"]
        if base_url is not None and base_url.strip():
            entry["base_url"] = base_url.strip()
        else:
            entry["base_url"] = entry.get("base_url") or preset["base_url"]
        entry["dim"] = new_dim

        scope_cfg.setdefault("providers", {})[provider_id] = entry
        scope_cfg["active_provider"] = provider_id
        if scope == "multimodal" and enabled is not None:
            scope_cfg["enabled"] = bool(enabled)

        cfg["updated_at"] = time.time()
        self._persist(cfg)
        self._cache = cfg
        logger.info(
            "Embedding {} 配置已更新: provider={}, model={}, dim={}",
            scope,
            provider_id,
            entry["model"],
            entry["dim"],
        )
        return {"ok": True, "config": self.get_public_config()}


embedding_config_service = EmbeddingConfigService()
