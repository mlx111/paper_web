"""多模态 embedding 服务：调用 DashScope 原生 multimodal-embedding API。

设计要点：
- DashScope multimodal-embedding-one-peace-v1 只支持 DashScope 原生 API
  （/api/v1/services/multimodal/multimodal-embedding/multimodal-embedding），
  不兼容 OpenAI 协议——不能复用 embodeding_service，需独立封装。
- 输入格式：{model, input: {contents: [{text, image: "data:image/png;base64,..."}]}}
- 输出：统一向量空间（默认 1024 维），支持纯文本、纯图像、图文混合输入。
- 跨模态对齐：文本和图像被编码到同一向量空间，用文本 query 检索图像向量合法
  （文本→图像跨模态检索路径）。
- 单图失败返回空 list（不抛异常），避免阻断索引；双轨降级为单轨（caption 块仍可用）。
- 配置 lazy 读取：每次调用从 embedding_config_service 读当前激活值，改配置立即生效。
- 仅依赖 requests（项目已有依赖），不引入额外包。
"""

from __future__ import annotations

import base64

import requests
from loguru import logger

from services.embedding_config_service import embedding_config_service


_REQUEST_TIMEOUT = 60

# DashScope 原生 multimodal-embedding 端点路径（拼在 base_url 后）
_ENDPOINT_PATH = "/services/multimodal/multimodal-embedding/multimodal-embedding"


class MultimodalEmbeddingService:
    """调用多模态 embedding 模型，生成图像 / 文本的统一向量。"""

    def __init__(self) -> None:
        # lazy 读取，不在 __init__ 缓存——配置改了立即生效
        pass

    @property
    def _params(self) -> dict:
        return embedding_config_service.get_multimodal_params()

    @property
    def enabled(self) -> bool:
        return bool(self._params.get("enabled", True))

    @property
    def model(self) -> str:
        return self._params.get("model") or "multimodal-embedding-one-peace-v1"

    @property
    def dim(self) -> int:
        return int(self._params.get("dim") or 1024)

    def _resolve_endpoint(self) -> tuple[str, str]:
        """返回 (url, api_key)。"""
        params = self._params
        base_url = (params.get("base_url") or "").rstrip("/")
        api_key = params.get("api_key") or ""
        return f"{base_url}{_ENDPOINT_PATH}", api_key

    # ---------- 对外入口 ----------

    def embed_image(self, image_bytes: bytes, ext: str) -> list[float]:
        """给图片字节生成向量。失败返回空 list。"""
        if not self.enabled:
            logger.debug("多模态 embedding 服务已禁用，跳过图像向量")
            return []
        if not image_bytes:
            return []
        url, api_key = self._resolve_endpoint()
        if not api_key:
            logger.warning("多模态 embedding api_key 为空，跳过图像向量")
            return []

        data_url = self._build_data_url(image_bytes, ext)
        payload = {
            "model": self.model,
            "input": {"contents": [{"image": data_url}]},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return self._call(url, headers, payload, kind="image")

    def embed_text(self, text: str) -> list[float]:
        """给文本生成向量（用于检索时编码 query）。失败返回空 list。"""
        if not self.enabled:
            return []
        if not text or not text.strip():
            return []
        url, api_key = self._resolve_endpoint()
        if not api_key:
            logger.warning("多模态 embedding api_key 为空，跳过文本向量")
            return []

        payload = {
            "model": self.model,
            "input": {"contents": [{"text": text}]},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return self._call(url, headers, payload, kind="text")

    # ---------- 内部工具 ----------

    def _call(self, url: str, headers: dict, payload: dict, kind: str) -> list[float]:
        """发请求并解析 DashScope 原生响应。失败返回空 list。"""
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            # 响应：{"output": {"embeddings": [{"index":0, "embedding":[...], "type":"text"|"image"}]}, "request_id": "..."}
            embeddings = data.get("output", {}).get("embeddings", [])
            if not embeddings:
                logger.warning("多模态 embedding 返回空 embeddings: {}", data)
                return []
            vec = embeddings[0].get("embedding") or []
            if not vec:
                logger.warning("多模态 embedding 向量为空: {}", data)
                return []
            logger.debug(
                "多模态 embedding({}) 生成成功，维度={}",
                kind,
                len(vec),
            )
            return vec
        except requests.RequestException as exc:
            logger.error("多模态 embedding 请求失败 ({}): {}", kind, exc)
            return []
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            logger.error("多模态 embedding 响应解析失败 ({}): {}", kind, exc)
            return []

    @staticmethod
    def _build_data_url(image_bytes: bytes, ext: str) -> str:
        """把图片字节编码为 data URL。"""
        clean_ext = (ext or "png").lower().lstrip(".")
        if clean_ext == "jpeg":
            clean_ext = "jpg"
        if clean_ext not in {"png", "jpg", "jpeg", "webp", "gif"}:
            clean_ext = "png"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/{clean_ext};base64,{encoded}"


multimodal_embedding_service = MultimodalEmbeddingService()
