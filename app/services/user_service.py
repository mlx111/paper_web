from models.user import User
from sqlalchemy import select,update,delete,exists
from sqlalchemy.ext.asyncio import AsyncSession
from schemas.user_schemsa import UserSchema
from pwdlib import PasswordHash
password_hasher = PasswordHash.recommended()
class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(self,user_schemas: UserSchema) -> User:
        async with self.session.begin():
            user=User(**user_schemas.model_dump())
            self.session.add(user)
            return user
    async def get_user_by_email(self, email: str) -> User|None:
        async with self.session.begin():
            user= await self.session.scalar(select(User).where(User.email == email))
            return user
    async def email_is_exist(self,email:str)->bool|None:
        async with self.session.begin():
            smt=select(exists().where(User.email == email))
            return await self.session.scalar(smt)
        
    async def get_user_by_username(self, username: str) -> User|None:
        async with self.session.begin():
            user= await self.session.scalar(select(User).where(User.username == username))
            return user
    
    async def username_is_exist(self,username:str)->bool|None:
        async with self.session.begin():
            smt=select(exists().where(User.username == username))
            return await self.session.scalar(smt)
    
    async def verify_password(self,username:str,password:str)->bool:
        async with self.session.begin():
            user= await self.session.scalar(select(User).where(User.username == username))
            if user is None:
                return False
            res=password_hasher.verify(password, user.password)
            return res
        
        