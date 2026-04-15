from core.mail import create_mail_instance
from fastapi_mail import FastMail
from sqlalchemy.ext.asyncio import AsyncSession
from models.base import async_session

from fastapi import Request
import redis.asyncio as redis


async def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis

async def get_session() -> AsyncSession:
    session = async_session()
    try:
        yield session
    finally:
        await session.close()

async def get_mail()->FastMail:
    return create_mail_instance()