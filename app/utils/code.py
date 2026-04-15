import random
def gen_code(length=6):
    """生成随机验证码"""
    return ''.join(random.choices('0123456789', k=length))

from fastapi import HTTPException
from core.redis import redis_client

async def verify_code(email:str,code:str):
    mail_key=f"mail_code:{email}"
    code_key=f"code:{code}"
    cached_code = await redis_client.get(code_key)
    cached_email=await redis_client.get(mail_key)
    if cached_code is None:
        return HTTPException(status_code=400, detail="验证码过期")
    if cached_code != code or cached_email != email:
        fails=await redis_client.incr(f"fail_count:{email}")
        if fails >= 5:
            await redis_client.set(mail_key,"",ex=300)  # 锁定邮箱5分钟
            await redis_client.delete(f"fail_count:{email}")
            raise HTTPException(status_code=400, detail="验证码错误过多，邮箱已锁定5分钟")
        raise HTTPException(status_code=400, detail="验证码错误")
    await redis_client.delete(mail_key)
    await redis_client.delete(code_key)
    return True