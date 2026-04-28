"""请求数据模型."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """对话请求."""

    id: str = Field(..., description="会话 ID", alias="Id")
    question: str = Field(..., description="用户问题", alias="Question")

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "Id": "session-123",
                "Question": "什么是向量数据库？",
            }
        },
    )


class ClearRequest(BaseModel):
    """清空会话请求."""

    session_id: str = Field(..., description="会话 ID", alias="sessionId")

    model_config = ConfigDict(populate_by_name=True)


class PresentationRequest(BaseModel):
    """Presentation 模块请求."""

    session_id: str = Field(..., description="会话 ID", alias="sessionId")
    topic: str | None = Field(default=None, description="演示主题")
    research_session_id: str | None = Field(default=None, description="研究会话 ID", alias="researchSessionId")
    target_pages: int | None = Field(default=None, description="目标页数", alias="targetPages")
    audience: str | None = Field(default=None, description="目标受众")
    tone: str | None = Field(default=None, description="演示风格")
    use_web_search: bool = Field(default=True, description="是否使用网页搜索", alias="useWebSearch")

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "sessionId": "presentation-123",
                "topic": "RAG在企业知识库中的应用分享",
                "researchSessionId": "research-session-abc",
                "targetPages": 6,
                "audience": "技术团队",
                "tone": "专业简洁",
                "useWebSearch": True,
            }
        },
    )


class PresentationMaterialInput(BaseModel):
    """Presentation 素材输入项."""

    source_type: str = Field(..., description="素材来源类型", alias="sourceType")
    material_type: str = Field(..., description="素材类型", alias="materialType")
    title: str | None = Field(default=None, description="素材标题")
    content: str | None = Field(default=None, description="素材正文")
    url: str | None = Field(default=None, description="素材链接")
    file_path: str | None = Field(default=None, description="本地文件路径", alias="filePath")
    mime_type: str | None = Field(default=None, description="MIME 类型", alias="mimeType")
    tags: list[str] = Field(default_factory=list, description="标签")
    notes: str | None = Field(default=None, description="备注")
    created_at: str | None = Field(default=None, description="创建时间", alias="createdAt")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

    model_config = ConfigDict(populate_by_name=True)


class PresentationMaterialsRequest(BaseModel):
    """Presentation 素材保存请求."""

    session_id: str = Field(..., description="会话 ID", alias="sessionId")
    materials: list[PresentationMaterialInput] = Field(default_factory=list, description="素材列表")

    model_config = ConfigDict(populate_by_name=True)
