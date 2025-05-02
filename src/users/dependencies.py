from typing import Optional

from fastapi import Header, HTTPException, Depends, status
from sqlalchemy import select

from src.database import SessionDep
from src.users.models import UserModel, RoleEnum


async def get_current_user(
    session: SessionDep,
    authorization: Optional[str] = Header(None)
) -> UserModel:
    if authorization is None or not authorization.startswith("TOKEN "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing or malformed"
        )
    
    token = authorization[len("TOKEN "):]

    user = await session.scalar(
        select(UserModel).where(UserModel.api_key == token)
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    return user

async def get_current_admin(user: UserModel = Depends(get_current_user)) -> UserModel:
    if user.role != RoleEnum.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return user