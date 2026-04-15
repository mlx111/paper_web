from fastapi import APIRouter,Depends,HTTPException
from dependencies import get_mail, get_session
from fastapi_mail import FastMail,MessageSchema,MessageType
from utils.code import gen_code,verify_code
from schemas.user_schemsa import UserSchema,RegisterIn,UsernameStr,RawPasswordStr
from sqlalchemy.ext.asyncio import AsyncSession
from core.redis import redis_client
from services.user_service import UserService
router = APIRouter(prefix="/auth",tags=["验证码相关接口"])

@router.post("/send_code")
async def send_code(email:str,
                    mail:FastMail=Depends(get_mail)):
    code = gen_code()
    mail_key=f"mail_code:{email}"
    code_key=f"code:{code}"
    if await redis_client.exists(code_key):
        return {"message":"验证码已发送，请稍后再试"}
    await redis_client.set(mail_key,email,ex=300)  # 间隔有效期为1分钟
    await redis_client.set(code_key,code,ex=300)  # 验证码有效期为5分钟
    # 这里可以添加发送验证码的逻辑，例如通过短信或邮件发送
    message=MessageSchema(subject="测试邮件", 
                          recipients=[email], 
                          body=code,
                          subtype=MessageType.plain)
    await mail.send_message(message)
    return {"message":"邮件发送成功"}

@router.post("/register")
async def register(
    data:RegisterIn,
    session:AsyncSession=Depends(get_session)
):
    user_repo=UserService(session)
    email_exist=await user_repo.email_is_exist(data.email)
    name_exist=await user_repo.username_is_exist(data.username)
    if name_exist:
        raise HTTPException(status_code=400, detail="用户名已被注册")
    if email_exist:
        raise HTTPException(status_code=400, detail="邮箱已被注册")
    result= await verify_code(data.email,data.code)
    if result is True:
        user_schema=UserSchema(username=data.username,email=data.email,password=data.password)
        user=await user_repo.create_user(user_schema)
        return {"message":"注册成功","user_id":user.id}
    
@router.post("/login")
async def login(
    username:UsernameStr,
    password:RawPasswordStr,
    session:AsyncSession=Depends(get_session)
):
    user_repo=UserService(session)
    user=await user_repo.get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=400, detail="用户名不存在")
    res=await user_repo.verify_password(username,password)
    if not res:
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    return {"message":"登录成功","username":username}