from typing import Annotated
import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import AsyncAdaptedQueuePool

from fastapi import Depends

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL not set')

if DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)

engine = create_async_engine(
    DATABASE_URL,
    echo=True,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=20,  # Максимальное количество соединений в пуле
    max_overflow=10,  # Максимальное количество дополнительных соединений
    pool_timeout=30,  # Таймаут ожидания соединения из пула
    pool_recycle=1800,  # Пересоздание соединений каждые 30 минут
    pool_pre_ping=True,  # Проверка соединений перед использованием
    isolation_level='REPEATABLE READ'  # Устанавливаем уровень изоляции
)

new_async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def get_session():
    async with new_async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

SessionDep = Annotated[AsyncSession, Depends(get_session)]

class Base(DeclarativeBase):
    pass