from fastapi import APIRouter

from src.database import SessionDep
from src.auth.models import UserModel 
from src.auth.schemas import UserRegistrationSchema, UserRegistrationResponceSchema
from src.auth.utils import generate_api_key


auth_router = APIRouter()

@auth_router.post('/api/v1/public/register', response_model=UserRegistrationResponceSchema)
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
