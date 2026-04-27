from typing import Any

import redis.asyncio as redis
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.mail import create_mail_instance
from models.base import async_session


async def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


async def get_session() -> AsyncSession:
    session = async_session()
    try:
        yield session
    finally:
        await session.close()


async def get_mail() -> Any:
    return create_mail_instance()
