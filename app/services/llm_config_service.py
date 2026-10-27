"""大模型（LLM）配置服务：供应商 / 模型名 / API Key / 接口地址 的运行时可配置化。

设计要点：
- 配置持久化到 app/data/llm_config.json（docker volume 挂载，重启不丢、不进镜像/不提交 git）。
- API Key 用 Fernet 对称加密后落盘；密钥保存在 app/data/.llm_secret（首次自动生成），
  GET 接口只回「是否已配置 + 掩码」，绝不返回明文；PUT 时 api_key 留空表示不修改。
- 供应商表驱动：统一使用 OpenAI 兼容 Chat Completions 客户端，所有 OpenAI 兼容服务
  （DashScope / DeepSeek / Kimi / OpenAI / 智谱 / 本地 Ollama 等）改 base_url+key+model 即可。
- 首次启动若配置文件不存在，用环境变量（.env）里的 DashScope 配置初始化默认值。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from settings.config import config

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_CONFIG_PATH = _DATA_DIR / "llm_config.json"
_SECRET_PATH = _DATA_DIR / ".llm_secret"

# 供应商预设：id / 显示名 / 默认 base_url / 默认模型 / 是否需要 API Key
PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "dashscope",
        "name": "阿里云百炼 DashScope (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen3.5-flash",
        "requires_api_key": True,
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "requires_api_key": True,
    },
    {
        "id": "moonshot",
        "name": "月之暗面 Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "requires_api_key": True,
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "requires_api_key": True,
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "requires_api_key": True,
    },
    {
        "id": "ollama",
        "name": "Ollama（本地）",
        "base_url": "http://host.docker.internal:11434/v1",
        "default_model": "qwen2.5:7b",
        "requires_api_key": False,
    },
    {
        "id": "custom",
        "name": "自定义（OpenAI 兼容）",
        "base_url": "",
        "default_model": "",
        "requires_api_key": True,
    },
]

_PROVIDER_MAP = {p["id"]: p for p in PROVIDERS}


class LLMConfigService:
    """读写当前激活的 LLM 配置，并对外提供工厂所需参数。"""

    def __init__(self) -> None:
        self._cache: dict[str, Any] | None = None

    # ---------- 加密 ----------
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
        except Exception as exc:  # 密钥损坏/更换时不致整个服务不可用
            logger.warning("LLM API Key 解密失败：{}", exc)
            return ""

    # ---------- 加载 / 保存 ----------
    def _default_config(self) -> dict[str, Any]:
        """首次启动：用 .env 里的 DashScope 配置初始化（按供应商分别存储）。"""
        dashscope = {
            "model": config.dashscope_model or "qwen3.5-flash",
            "base_url": config.dashscope_api_base or _PROVIDER_MAP["dashscope"]["base_url"],
            "api_key_enc": self._encrypt(config.DASHSCOPE_API_KEY or ""),
        }
        return {
            "active_provider": "dashscope",
            "providers": {"dashscope": dashscope},
            "updated_at": time.time(),
        }

    def _migrate_if_needed(self, cfg: dict[str, Any]) -> dict[str, Any]:
        """兼容旧版扁平配置：{provider, model, base_url, api_key_enc} → 按供应商分存。"""
        if "providers" in cfg and isinstance(cfg.get("providers"), dict):
            cfg.setdefault("active_provider", cfg.get("provider") or "dashscope")
            return cfg
        # 旧格式迁移
        provider_id = cfg.get("provider") or "dashscope"
        entry = {
            "model": cfg.get("model") or "",
            "base_url": cfg.get("base_url") or "",
            "api_key_enc": cfg.get("api_key_enc") or "",
        }
        migrated = {
            "active_provider": provider_id,
            "providers": {provider_id: entry},
            "updated_at": cfg.get("updated_at") or time.time(),
        }
        logger.info("LLM 配置已从旧格式迁移为按供应商分存")
        return migrated

    def _load(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if _CONFIG_PATH.exists():
            try:
                data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
                data = self._migrate_if_needed(data)
                self._cache = data
                return self._cache
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("LLM 配置文件读取失败，回退默认：{}", exc)
        self._cache = self._default_config()
        self._persist(self._cache)
        return self._cache

    def _persist(self, data: dict[str, Any]) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_PATH)

    def _get_provider_entry(self, cfg: dict[str, Any], provider_id: str) -> dict[str, Any]:
        """获取指定供应商的配置条目；不存在则返回空条目（不创建）。"""
        return cfg.get("providers", {}).get(provider_id, {})

    def _upsert_provider_entry(self, cfg: dict[str, Any], provider_id: str, entry: dict[str, Any]) -> None:
        cfg.setdefault("providers", {})[provider_id] = entry

    # ---------- 对外：工厂用的明文参数 ----------
    def get_active_params(self) -> dict[str, Any]:
        """返回当前激活供应商的明文字段（供模型工厂实例化用）。"""
        cfg = self._load()
        provider_id = cfg.get("active_provider") or "dashscope"
        preset = _PROVIDER_MAP.get(provider_id, _PROVIDER_MAP["custom"])
        entry = self._get_provider_entry(cfg, provider_id)
        return {
            "provider": provider_id,
            "model": entry.get("model") or preset["default_model"],
            "base_url": entry.get("base_url") or preset["base_url"],
            "api_key": self._decrypt(entry.get("api_key_enc") or ""),
        }

    # ---------- 对外：页面用的脱敏配置 ----------
    def get_public_config(self) -> dict[str, Any]:
        cfg = self._load()
        active_id = cfg.get("active_provider") or "dashscope"
        active = self.get_active_params()
        api_key = active["api_key"]

        # 按供应商返回各自的脱敏配置，前端切换供应商时可带出已保存的值
        provider_configs: dict[str, Any] = {}
        for pid, entry in cfg.get("providers", {}).items():
            key = self._decrypt(entry.get("api_key_enc") or "")
            provider_configs[pid] = {
                "model": entry.get("model") or "",
                "base_url": entry.get("base_url") or "",
                "has_api_key": bool(key),
                "api_key_masked": self._mask(key),
            }

        return {
            "provider": active_id,
            "model": active["model"],
            "base_url": active["base_url"],
            "has_api_key": bool(api_key),
            "api_key_masked": self._mask(api_key),
            "provider_configs": provider_configs,
            "providers": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "base_url": p["base_url"],
                    "default_model": p["default_model"],
                    "requires_api_key": p["requires_api_key"],
                }
                for p in PROVIDERS
            ],
        }

    @staticmethod
    def _mask(key: str) -> str:
        if not key:
            return ""
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"

    # ---------- 对外：更新配置 ----------
    def update_config(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """保存指定供应商的配置（只更新该供应商条目，不影响其他供应商）。
        api_key 留空表示不修改该供应商已保存的 Key。"""
        cfg = self._load()
        provider_id = (provider or cfg.get("active_provider") or "dashscope").strip()
        preset = _PROVIDER_MAP.get(provider_id, _PROVIDER_MAP["custom"])
        entry = dict(self._get_provider_entry(cfg, provider_id))

        new_model = (model or "").strip() or entry.get("model") or preset["default_model"]
        if base_url is not None and base_url.strip():
            new_base = base_url.strip()
        else:
            new_base = entry.get("base_url") or preset["base_url"]

        # api_key：留空表示不修改，保留该供应商原密钥
        if api_key and api_key.strip():
            entry["api_key_enc"] = self._encrypt(api_key.strip())

        entry["model"] = new_model
        entry["base_url"] = new_base
        self._upsert_provider_entry(cfg, provider_id, entry)
        cfg["active_provider"] = provider_id
        cfg["updated_at"] = time.time()

        self._persist(cfg)
        self._cache = cfg
        logger.info("LLM 配置已更新：provider={}, model={}, base_url={}", provider_id, new_model, new_base)
        return self.get_public_config()

    # ---------- 对外：连通性测试 / 拉取模型列表 ----------
    def _resolve_params(
        self,
        provider: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """根据表单输入解析出 provider / base_url / api_key：
        - 填了 api_key 用传入值；没填用该供应商已保存的 Key
        - base_url / provider 优先用传入值，否则沿用该供应商已保存/供应商默认
        """
        cfg = self._load()
        provider_id = (provider or cfg.get("active_provider") or "dashscope").strip()
        preset = _PROVIDER_MAP.get(provider_id, _PROVIDER_MAP["custom"])
        entry = self._get_provider_entry(cfg, provider_id)

        saved_key = self._decrypt(entry.get("api_key_enc") or "")
        if api_key and api_key.strip():
            use_key = api_key.strip()
        else:
            use_key = saved_key

        if base_url and base_url.strip():
            use_base = base_url.strip()
        else:
            use_base = entry.get("base_url") or preset["base_url"]

        return {
            "provider": provider_id,
            "base_url": use_base,
            "api_key": use_key,
            "preset": preset,
        }

    def test_connection(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """用给定（或当前）配置发一个极简请求，返回是否连通 + 延迟。"""
        params = self._resolve_params(provider, base_url, api_key)
        preset = params["preset"]
        params["model"] = (model or "").strip() or preset["default_model"]

        if preset["requires_api_key"] and not params["api_key"]:
            return {"ok": False, "message": "该供应商需要 API Key，但未配置"}

        start = time.time()
        try:
            from models.factory import UniversalChatOpenAI
            from core.http_client_factory import create_llm_async_http_client, create_llm_http_client
            from pydantic import SecretStr

            llm = UniversalChatOpenAI(
                model=params["model"],
                base_url=params["base_url"],
                api_key=SecretStr(params["api_key"] or "not-required"),
                temperature=0,
                streaming=False,
                provider=params["provider"],
                preserve_reasoning_content=params["provider"] in {"deepseek", "dashscope", "moonshot", "zhipu", "custom"},
                max_tokens=8,
                use_responses_api=False,
                http_client=create_llm_http_client(),
                http_async_client=create_llm_async_http_client(),
            )
            resp = llm.invoke("ping")
            latency_ms = int((time.time() - start) * 1000)
            content = getattr(resp, "content", str(resp))
            return {
                "ok": True,
                "message": f"连接成功，模型回复：{str(content)[:60]}",
                "latency_ms": latency_ms,
                "model": params["model"],
            }
        except Exception as exc:
            latency_ms = int((time.time() - start) * 1000)
            return {"ok": False, "message": f"连接失败：{str(exc)[:300]}", "latency_ms": latency_ms}

    def fetch_models(
        self,
        provider: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """调用 OpenAI 兼容的 /models 接口，拉取该账号下可用模型列表。"""
        params = self._resolve_params(provider, base_url, api_key)
        base_url = params["base_url"].rstrip("/")
        preset = params["preset"]

        if preset["requires_api_key"] and not params["api_key"]:
            return {"ok": False, "message": "该供应商需要 API Key，但未配置", "models": []}

        if not base_url:
            return {"ok": False, "message": "缺少 Base URL", "models": []}

        # Ollama 走自身的 /api/tags，其他 OpenAI 兼容走 {base_url}/models
        is_ollama = params["provider"] == "ollama"
        try:
            import httpx

            headers = {}
            if params["api_key"]:
                headers["Authorization"] = f"Bearer {params['api_key']}"

            if is_ollama:
                # base_url 形如 http://host:11434/v1，回退到根 /api/tags
                ollama_root = base_url[:-3] if base_url.endswith("/v1") else base_url
                url = f"{ollama_root}/api/tags"
                resp = httpx.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            else:
                url = f"{base_url}/models"
                resp = httpx.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("id") for m in data.get("data", []) if m.get("id")]

            models = sorted(set(models))
            return {"ok": True, "models": models, "count": len(models)}
        except Exception as exc:
            return {"ok": False, "message": f"获取模型列表失败：{str(exc)[:300]}", "models": []}


llm_config_service = LLMConfigService()
