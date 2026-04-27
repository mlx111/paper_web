"""请求数据模型."""

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
    topic: str = Field(..., description="演示主题")
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
                "targetPages": 6,
                "audience": "技术团队",
                "tone": "专业简洁",
                "useWebSearch": True,
            }
        },
    )
