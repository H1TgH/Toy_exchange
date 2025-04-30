import pytest
from src.auth.models import UserModel
from sqlalchemy import select

@pytest.mark.asyncio
async def test_register_user(client, session):
    test_data = {"name": "Test User"}
    
    response = await client.post(
        "/api/v1/public/register",
        json=test_data
    )
    
    assert response.status_code == 200
    response_data = response.json()
    
    assert "id" in response_data
    assert response_data["name"] == "Test User"
    assert response_data["role"] == "USER"
    assert len(response_data["api_key"]) == 43
    
    # Проверка в базе данных
    user = await session.get(UserModel, response_data["id"])
    assert user is not None
    assert user.name == "Test User"

@pytest.mark.asyncio
async def test_register_user_short_name(client):
    test_data = {"name": "A"}
    
    response = await client.post(
        "/api/v1/public/register",
        json=test_data
    )
    
    assert response.status_code == 422
    assert "Name too short" in str(response.json()["detail"])