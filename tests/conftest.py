import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import engine, Base, new_async_session


# HTTP клиент
@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

# Сессия БД
@pytest_asyncio.fixture
async def session():
    async with new_async_session() as session:
        yield session
