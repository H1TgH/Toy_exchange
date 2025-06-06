from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select

from src.database import SessionDep
from src.balance.models import BalanceModel
from src.users.models import UserModel
from src.balance.schemas import BalanceSchema
from src.users.dependencies import get_current_admin
from src.schemas import OkResponseSchema

balance_router = APIRouter()

@balance_router.post('/api/v1/admin/balance/deposit', response_model=OkResponseSchema, tags=['admin'])
async def replenish_balance(
    balance_data: BalanceSchema, 
    session: SessionDep,
    current_admin: UserModel = Depends(get_current_admin)
):
    user = await session.scalar(
        select(UserModel).where(UserModel.id == balance_data.user_id)
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    balance = await session.scalar(
        select(BalanceModel).where(
            BalanceModel.user_id == balance_data.user_id,
            BalanceModel.ticker == balance_data.ticker
        )
    )
    
    if balance:
        balance.amount += balance_data.amount
    else:
        balance = BalanceModel(
            user_id=balance_data.user_id,
            ticker=balance_data.ticker,
            amount=balance_data.amount
        )
        session.add(balance)

    await session.commit()

    return {'success': True}

@balance_router.post('/api/v1/admin/balance/withdraw', response_model=OkResponseSchema, tags=['admin', 'balance'])
async def withdraw_balance(
    balance_data: BalanceSchema,
    session: SessionDep,
    current_admin: UserModel = Depends(get_current_admin)
):
    user = await session.scalar(
        select(UserModel)
        .where(UserModel.id == balance_data.user_id)
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    balance = await session.scalar(
        select(BalanceModel)
        .where(
            BalanceModel.user_id == balance_data.user_id,
            BalanceModel.ticker == balance_data.ticker
        )
    )
    
    if not balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No balance found for ticker {balance_data.ticker}"
        )

    if balance.amount < balance_data.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient balance for withdrawal"
        )

    balance.amount -= balance_data.amount
    await session.commit()

    return {'success': True}