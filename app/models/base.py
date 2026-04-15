from sqlalchemy import DateTime,  func
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column,sessionmaker
from sqlalchemy import MetaData
from settings.url import DB_URL

engine=create_async_engine(DB_URL,echo=True,
                           pool_size=10,max_overflow=20,
                           pool_timeout=30, pool_recycle=3600)

async_session=sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True
)

class Base(DeclarativeBase):
    create_time: Mapped[datetime] = mapped_column(DateTime, 
        insert_default=func.now(), default=func.now, comment="创建时间")
    metadata=MetaData(
        naming_convention={#索引
        "ix": "ix_%(column_0_label)s",
        #唯一索引
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        #检查约束
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        #外键
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        #主键
        "pk": "pk_%(table_name)s"}
    )