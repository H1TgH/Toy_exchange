from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from src.database import SessionDep
from src.users.models import UserModel 
from src.users.schemas import UserRegistrationSchema, UserRegistrationResponceSchema
from src.users.utils import generate_api_key
from src.users.dependencies import get_current_admin


auth_router = APIRouter()

@auth_router.post('/api/v1/public/register', response_model=UserRegistrationResponceSchema, tags=['public'])
async def register_user(
    user_data: UserRegistrationSchema,
    session: SessionDep
):
    new_user_api_key = generate_api_key()
    new_user = UserModel(
        name = user_data.name,
        api_key = new_user_api_key
    )

    session.add(new_user)
    await session.commit()

    return {
        'id': new_user.id,
        'name': new_user.name,
        'role': new_user.role,
        'api_key': new_user_api_key
    }

@auth_router.delete('/api/v1/admin/user/{user_id}', response_model=UserRegistrationResponceSchema, tags=['admin', 'user'])
async def delete_user(
    session: SessionDep,
    user_id: str,
    admin_user = Depends(get_current_admin)
):
    user = await session.scalar(select(UserModel).where(UserModel.id == user_id))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='User with user_id not found'
        )
    
    deleted_user_data = {
        "id": str(user.id),
        "name": user.name,
        "role": user.role,
        "api_key": user.api_key,
    }
    
    await session.delete(user)
    await session.commit()

    return deleted_user_data