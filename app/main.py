from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from contextlib import asynccontextmanager
import redis.asyncio as redis
from settings.url import REDIS_URL
from routers.auth import router as auth_router
from routers.agent import router as agent_router
from routers.elasticsearch import router as elasticsearch_router
from routers.file import router as file_router
from loguru import logger
from settings.config import config
from services.mlivus_client_service import mlivus_client_service
from services.vector_index_service import vector_index_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True)

    logger.info("=" * 60)
    logger.info(f"🚀 {config.app_name} v{config.app_version} 启动中...")
    logger.info(f"📝 环境: {'开发' if config.debug else '生产'}")
    logger.info(f"🌐 监听地址: http://{config.host}:{config.port}")
    logger.info(f"📚 API 文档: http://{config.host}:{config.port}/docs")

    # 连接 Milvus
    logger.info("🔌 正在连接 Milvus...")
    mlivus_client_service.connect()
    logger.info("✅ Milvus 连接成功")

    logger.info("📚 正在扫描 uploads 目录并自动切片入库...")
    index_result = vector_index_service.sync_directory_incrementally()
    logger.info(
        "📚 uploads 扫描完成: 总数={}, 成功={}, 失败={}",
        index_result.total_files,
        index_result.success_count,
        index_result.fail_count,
    )

    logger.info("=" * 60)
    try:
        yield
    finally:
        try:
            await app.state.redis.aclose()
            logger.info("Redis 连接已关闭")
        except Exception as exc:
            logger.error("关闭 Redis 连接失败: {}", exc)

        try:
            logger.info("🔌 正在关闭 Milvus 连接...")
            mlivus_client_service.close()
        except Exception as exc:
            logger.error("关闭 Milvus 连接失败: {}", exc)

        logger.info(f"👋 {config.app_name} 关闭")


app = FastAPI(title="我的论文网", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.include_router(auth_router)
app.include_router(agent_router)
app.include_router(elasticsearch_router)
app.include_router(file_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host=config.host, port=config.port, reload=config.debug)



