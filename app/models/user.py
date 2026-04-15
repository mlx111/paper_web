
from sqlalchemy.orm import Mapped, mapped_column,relationship
from .base import Base
from sqlalchemy import String,Integer,ForeignKey
from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer,primary_key=True, comment="用户id")
    username: Mapped[str] = mapped_column(String(255), unique=True, comment="用户名")
    email: Mapped[str] = mapped_column(String(255), unique=True, comment="邮箱")
    _password: Mapped[str] = mapped_column(String(255), comment="密码")
    
    emails:Mapped["Email"]=relationship("Email", back_populates="user")  # 反向关系，获取用户对应的邮箱列表
    def __init__(self, *args,**kwargs):
        password=kwargs.pop("password")
        super().__init__(*args,**kwargs)
        if password:
            self.password=password #会调用setter方法进行加密存储
        
    @property
    def password(self):
        return self._password
    
    @password.setter
    def password(self, raw_password):
        self._password = password_hasher.hash(raw_password)
        
    def check_password(self, raw_password):
        return password_hasher.verify(raw_password, self.password)
    
class Email(Base):
    __tablename__ = "emails"
    id: Mapped[int] = mapped_column(Integer,primary_key=True, comment="邮箱id")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), comment="用户id")
    email: Mapped[str] = mapped_column(String(255), unique=True, comment="邮箱地址")
    email_code: Mapped[str] = mapped_column(String(255), comment="邮箱验证码")
    user: Mapped["User"] = relationship("User", back_populates="emails")  # 反向关系，获取邮箱对应的用户