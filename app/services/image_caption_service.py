"""图像 caption 生成服务。

调用视觉大模型（默认 qwen-vl-max，DashScope 兼容 OpenAI 协议）为论文 PDF/DOCX
中提取的图片生成中文文字描述。生成的 caption 会在索引阶段作为独立块写入
Milvus，使图片本身可被语义检索（多模态 RAG）。

设计要点：
- 仅依赖 requests（项目已有依赖），不引入额外包。
- 单图生成失败不抛异常，返回空字符串，避免拖垮整篇索引。
- 视觉模型配置可经环境变量覆盖；缺省复用 DashScope 文本模型 key/base。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

from settings.config import config
from services.chunk_image_store_service import default_chunk_image_store


# 图片大小下限（qwen-vl-max 要求 >10x10），字节维度近似阈值
_MIN_IMAGE_BYTES = 64
# 单次 caption 请求超时（秒）—— 视觉模型响应较慢，给足 60s
_REQUEST_TIMEOUT = 60
# 单图 caption 最大字符数（避免长篇描述污染索引）
_MAX_CAPTION_LEN = 600


class ImageCaptionService:
    """为图片生成文字描述。"""

    def __init__(self) -> None:
        # vision 模型配置改为 lazy 读取（property），不在 __init__ 缓存
        logger.info("图像 caption 服务初始化完成（lazy 读取配置）")

    # ---- lazy 读取：每次从 config 读当前值 ----
    @property
    def model(self) -> str:
        return config.VISION_MODEL

    @property
    def base_url(self) -> str:
        return config.VISION_API_BASE

    @property
    def api_key(self) -> str:
        return config.VISION_API_KEY

    @property
    def enabled(self) -> bool:
        return config.VISION_ENABLED

    # ---------- 对外入口 ----------

    def caption_placeholder(self, placeholder: str) -> str:
        """根据占位符定位本地图片，生成 caption 并写回映射。

        失败时返回空字符串；映射里 caption 字段保持空字符串，方便排查。
        """
        if not self.enabled:
            logger.debug("图像 caption 服务已禁用，跳过: {}", placeholder)
            return ""

        image_path = self._resolve_image_path(placeholder)
        if image_path is None:
            logger.warning("未找到占位符对应的图片文件，跳过 caption: {}", placeholder)
            return ""

        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            logger.warning("读取图片字节失败: {}，错误: {}", image_path, exc)
            return ""

        if len(image_bytes) < _MIN_IMAGE_BYTES:
            logger.info("图片过小（{} 字节），跳过 caption: {}", len(image_bytes), placeholder)
            return ""

        ext = image_path.suffix.lstrip(".").lower() or "png"
        caption = self.generate_caption(image_bytes, ext)
        if caption:
            default_chunk_image_store.update_caption(placeholder, caption)
            logger.info(
                "图像 caption 生成成功: {} -> {}",
                placeholder,
                caption[:80] + ("..." if len(caption) > 80 else ""),
            )
        else:
            logger.warning("图像 caption 生成失败（返回空）: {}", placeholder)
        return caption

    def generate_caption(self, image_bytes: bytes, ext: str) -> str:
        """调用视觉模型为单张图片生成中文描述。"""
        if not self.enabled:
            return ""
        if not self.api_key:
            logger.warning("视觉模型 api_key 为空，无法生成 caption")
            return ""
        if not self.base_url:
            logger.warning("视觉模型 base_url 为空，无法生成 caption")
            return ""

        data_url = self._build_data_url(image_bytes, ext)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "请用中文简洁、客观地描述这张论文图片的核心内容，"
                                "包含图表类型、关键数据/对象和能识别出的主题文字。"
                                "不要复述“这是一张图片”，直接输出描述，不超过 150 字。"
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            # 论文图表描述需要稳定输出，温度调低
            "temperature": 0.2,
            "max_tokens": 512,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            caption = self._normalize_caption(content)
            if not caption:
                logger.warning("视觉模型返回空内容: {}", data)
            return caption
        except requests.RequestException as exc:
            logger.error("视觉模型请求失败: {}", exc)
            return ""
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            logger.error("视觉模型响应解析失败: {}", exc)
            return ""

    # ---------- 内部工具 ----------

    def _resolve_image_path(self, placeholder: str) -> Optional[Path]:
        """从映射里反查图片路径。"""
        mapping = default_chunk_image_store._load_mapping()
        record = mapping.get(placeholder)
        if not record:
            return None
        path_str = record.get("image_path") or ""
        if not path_str:
            return None
        path = Path(path_str)
        return path if path.exists() else None

    @staticmethod
    def _build_data_url(image_bytes: bytes, ext: str) -> str:
        """把图片字节编码为 OpenAI 兼容的 data URL。"""
        clean_ext = (ext or "png").lower().lstrip(".")
        if clean_ext == "jpeg":
            clean_ext = "jpg"
        if clean_ext not in {"png", "jpg", "jpeg", "webp", "gif"}:
            # 不支持的格式回退为 png（多数 PyMuPDF 提取的图就是 png）
            clean_ext = "png"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/{clean_ext};base64,{encoded}"

    @staticmethod
    def _normalize_caption(content) -> str:
        """规整模型输出：去首尾空白，限长，去多余换行。"""
        if not content:
            return ""
        if isinstance(content, list):
            # 部分视觉模型把 content 拆成 [{"type":"text","text":...}]
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or ""))
                else:
                    parts.append(str(item))
            content = "".join(parts)
        caption = str(content).strip()
        # 压缩多余空白
        caption = " ".join(caption.split())
        if len(caption) > _MAX_CAPTION_LEN:
            caption = caption[:_MAX_CAPTION_LEN].rstrip() + "..."
        return caption


image_caption_service = ImageCaptionService()
