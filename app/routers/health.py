"""Health check API route."""

from fastapi import APIRouter

from services.health_service import build_health_report
from services.mlivus_client_service import mlivus_client_service
from settings.config import config
from settings.url import DB_URL, REDIS_URL


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Return API and dependency health information."""
    return build_health_report(
        app_name=config.app_name,
        app_version=config.app_version,
        debug=config.debug,
        model_key=config.dashscope_api_key,
        milvus_checker=mlivus_client_service.health_check,
        redis_url=REDIS_URL,
        db_url=DB_URL,
    )
