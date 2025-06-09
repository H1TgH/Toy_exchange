from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select

from src.database import SessionDep
from src.balance.models import BalanceModel
from src.instruments.models import InstrumentModel
from src.users.models import UserModel
from src.balance.schemas import BalanceSchema
from src.users.dependencies import get_current_admin, get_current_user
from src.schemas import OkResponseSchema
from src.logger import logger


balance_router = APIRouter()

@balance_router.get('/api/v1/balance', response_model=dict[str, int], tags=['balance'])
async def get_balances(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user)
):
    logger.info(f'Пользователь {current_user.id} запрашивает свои балансы')
    balances = await session.scalars(
        select(BalanceModel)
        .where(BalanceModel.user_id == current_user.id)
    )
    balances_dict = {balance.ticker: int(balance.amount) for balance in balances.all()}
    logger.info(f'Пользователь {current_user.id} получил балансы: {balances_dict}')
    return balances_dict

@balance_router.post('/api/v1/admin/balance/deposit', response_model=OkResponseSchema, tags=['admin', 'balance'])
async def deposit_balance(
    balance_data: BalanceSchema, 
    session: SessionDep,
    current_admin: UserModel = Depends(get_current_admin)
):
    logger.info(f'Админ {current_admin.id} пытается пополнить баланс пользователя {balance_data.user_id} на {balance_data.amount} {balance_data.ticker}')
    
    user = await session.scalar(
        select(UserModel)
        .where(UserModel.id == balance_data.user_id)
    )
    
    if not user:
        logger.warning(f'Попытка пополнения баланса: пользователь {balance_data.user_id} не найден')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Invalid user_id value'
        )

    ticker = await session.scalar(
        select(InstrumentModel)
        .where(InstrumentModel.ticker == balance_data.ticker)
    )

    if not ticker:
        logger.warning(f'Попытка пополнения баланса: тикер {balance_data.ticker} не найден')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Invalid ticker value'
        )

    balance = await session.scalar(
        select(BalanceModel).where(
            BalanceModel.user_id == balance_data.user_id,
            BalanceModel.ticker == balance_data.ticker
        )
    )
    
    if balance:
        balance.amount += balance_data.amount
        logger.info(f'Баланс пользователя {balance_data.user_id} по тикеру {balance_data.ticker} увеличен на {balance_data.amount}')
    else:
        balance = BalanceModel(
            user_id=balance_data.user_id,
            ticker=balance_data.ticker,
            amount=balance_data.amount
        )
        session.add(balance)
        logger.info(f'Создан новый баланс для пользователя {balance_data.user_id} по тикеру {balance_data.ticker} с суммой {balance_data.amount}')

    await session.commit()
    logger.info(f'Баланс успешно пополнен администратором {current_admin.id}')
    return {'success': True}

@balance_router.post('/api/v1/admin/balance/withdraw', response_model=OkResponseSchema, tags=['admin', 'balance'])
async def withdraw_balance(
    balance_data: BalanceSchema,
    session: SessionDep,
    current_admin: UserModel = Depends(get_current_admin)
):
    logger.info(f'Админ {current_admin.id} пытается списать {balance_data.amount} {balance_data.ticker} с баланса пользователя {balance_data.user_id}')
    
    user = await session.scalar(
        select(UserModel)
        .where(UserModel.id == balance_data.user_id)
    )
    
    if not user:
        logger.warning(f'Попытка списания баланса: пользователь {balance_data.user_id} не найден')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='User not found'
        )

    balance = await session.scalar(
        select(BalanceModel)
        .where(
            BalanceModel.user_id == balance_data.user_id,
            BalanceModel.ticker == balance_data.ticker
        )
    )
    
    if not balance:
        logger.warning(f'Попытка списания баланса: баланс по тикеру {balance_data.ticker} не найден у пользователя {balance_data.user_id}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'No balance found for ticker {balance_data.ticker}'
        )

    if balance.amount < balance_data.amount:
        logger.warning(f'Попытка списания баланса: недостаточно средств у пользователя {balance_data.user_id} по тикеру {balance_data.ticker}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Insufficient balance for withdrawal'
        )

    balance.amount -= balance_data.amount
    await session.commit()
    logger.info(f'Баланс пользователя {balance_data.user_id} по тикеру {balance_data.ticker} уменьшен на {balance_data.amount} администратором {current_admin.id}')
    return {'success': True}