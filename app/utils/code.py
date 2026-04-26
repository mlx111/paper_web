import random

from fastapi import HTTPException

from core.redis import redis_client


CODE_TTL_SECONDS = 300
FAIL_LIMIT = 5


def gen_code(length=6):
    """Generate a numeric verification code."""
    return "".join(random.choices("0123456789", k=length))


def get_mail_code_key(email: str) -> str:
    return f"mail_code:{email}"


def get_fail_count_key(email: str) -> str:
    return f"fail_count:{email}"


async def verify_code(email: str, code: str):
    mail_key = get_mail_code_key(email)
    fail_key = get_fail_count_key(email)
    cached_code = await redis_client.get(mail_key)

    if cached_code is None:
        raise HTTPException(status_code=400, detail="验证码已过期")

    if cached_code != code:
        fails = await redis_client.incr(fail_key)
        if fails == 1:
            await redis_client.expire(fail_key, CODE_TTL_SECONDS)
        if fails >= FAIL_LIMIT:
            await redis_client.delete(mail_key)
            await redis_client.delete(fail_key)
            raise HTTPException(status_code=400, detail="验证码错误过多，请重新获取")
        raise HTTPException(status_code=400, detail="验证码错误")

    await redis_client.delete(mail_key)
    await redis_client.delete(fail_key)
    return True
