from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from uuid import UUID

from src.database import SessionDep
from src.users.models import UserModel 
from src.users.schemas import UserRegistrationSchema, UserRegistrationResponceSchema
from src.users.utils import generate_api_key
from src.users.dependencies import get_current_admin
from src.logger import logger


auth_router = APIRouter()

@auth_router.post('/api/v1/public/register', response_model=UserRegistrationResponceSchema, tags=['public'])
async def register_user(
    user_data: UserRegistrationSchema,
    session: SessionDep
):
    try:
        logger.info(f'[POST /api/v1/public/register] Начало регистрации пользователя: name={user_data.name}')
        
        new_user_api_key = generate_api_key()
        logger.debug(f'[POST /api/v1/public/register] Сгенерирован API ключ для пользователя: name={user_data.name}')
        
        new_user = UserModel(
            name=user_data.name,
            api_key=new_user_api_key
        )

        session.add(new_user)
        await session.commit()
        logger.info(f'[POST /api/v1/public/register] Пользователь успешно создан: id={new_user.id}, name={new_user.name}, role={new_user.role}')

        return {
            'id': new_user.id,
            'name': new_user.name,
            'role': new_user.role,
            'api_key': new_user_api_key
        }
    except Exception as e:
        logger.error(f'[POST /api/v1/public/register] Ошибка при регистрации пользователя: name={user_data.name}, error={str(e)}', exc_info=True)
        raise

@auth_router.delete('/api/v1/admin/user/{user_id}', response_model=UserRegistrationResponceSchema, tags=['admin', 'user'])
async def delete_user(
    session: SessionDep,
    user_id: UUID,
    admin_user=Depends(get_current_admin)
):
    try:
        logger.info(f'[DELETE /api/v1/admin/user/{user_id}] Начало удаления пользователя: user_id={user_id}, admin_id={admin_user.id}, admin_email={admin_user.email}')
        
        user = await session.scalar(select(UserModel).where(UserModel.id == user_id))

        if not user:
            logger.warning(f'[DELETE /api/v1/admin/user/{user_id}] Попытка удаления несуществующего пользователя')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='User not found'
            )
        
        logger.info(f'[DELETE /api/v1/admin/user/{user_id}] Пользователь найден: name={user.name}, role={user.role}')
        
        deleted_user_data = {
            'id': str(user.id),
            'name': user.name,
            'role': user.role,
            'api_key': user.api_key,
        }
        
        await session.delete(user)
        await session.commit()

        logger.info(f'[DELETE /api/v1/admin/user/{user_id}] Пользователь успешно удалён: name={user.name}, role={user.role}')

        return deleted_user_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'[DELETE /api/v1/admin/user/{user_id}] Ошибка при удалении пользователя: error={str(e)}', exc_info=True)
        raise