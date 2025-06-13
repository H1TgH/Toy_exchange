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
    logger.info(f'[GET /api/v1/balance] Начало запроса балансов для пользователя {current_user.id}')
    try:
        balances = await session.scalars(
            select(BalanceModel)
            .where(BalanceModel.user_id == current_user.id)
        )
        balances_dict = {balance.ticker: int(balance.amount) for balance in balances.all()}
        logger.info(f'[GET /api/v1/balance] Успешно получены балансы для пользователя {current_user.id}: {balances_dict}')
        return balances_dict
    except Exception as e:
        logger.error(f'[GET /api/v1/balance] Ошибка при получении балансов для пользователя {current_user.id}: {str(e)}')
        raise

@balance_router.post('/api/v1/admin/balance/deposit', response_model=OkResponseSchema, tags=['admin', 'balance'])
async def deposit_balance(
    balance_data: BalanceSchema, 
    session: SessionDep,
    current_admin: UserModel = Depends(get_current_admin)
):
    logger.info(f'[POST /api/v1/admin/balance/deposit] Админ {current_admin.id}) инициировал пополнение баланса: user_id={balance_data.user_id}, ticker={balance_data.ticker}, amount={balance_data.amount}')
    
    try:
        user = await session.scalar(
            select(UserModel)
            .where(UserModel.id == balance_data.user_id)
        )
        
        if not user:
            logger.warning(f'[POST /api/v1/admin/balance/deposit] Попытка пополнения баланса: пользователь {balance_data.user_id} не найден')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Invalid user_id value'
            )

        logger.info(f'[POST /api/v1/admin/balance/deposit] Найден пользователь: id={user.id}')

        ticker = await session.scalar(
            select(InstrumentModel)
            .where(InstrumentModel.ticker == balance_data.ticker)
        )

        if not ticker:
            logger.warning(f'[POST /api/v1/admin/balance/deposit] Попытка пополнения баланса: тикер {balance_data.ticker} не найден')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Invalid ticker value'
            )

        logger.info(f'[POST /api/v1/admin/balance/deposit] Найден тикер: {ticker.ticker}')

        balance = await session.scalar(
            select(BalanceModel).where(
                BalanceModel.user_id == balance_data.user_id,
                BalanceModel.ticker == balance_data.ticker
            )
        )
        
        if balance:
            old_amount = balance.amount
            balance.amount += balance_data.amount
            balance.available += balance_data.amount
            logger.info(f'[POST /api/v1/admin/balance/deposit] Обновление существующего баланса: user_id={balance_data.user_id}, ticker={balance_data.ticker}, old_amount={old_amount}, new_amount={balance.amount}')
        else:
            balance = BalanceModel(
                user_id=balance_data.user_id,
                ticker=balance_data.ticker,
                amount=balance_data.amount,
                available=balance_data.amount
            )
            session.add(balance)
            logger.info(f'[POST /api/v1/admin/balance/deposit] Создание нового баланса: user_id={balance_data.user_id}, ticker={balance_data.ticker}, amount={balance_data.amount}')

        await session.commit()
        logger.info(f'[POST /api/v1/admin/balance/deposit] Успешное пополнение баланса: user_id={balance_data.user_id}, ticker={balance_data.ticker}, amount={balance_data.amount}, admin_id={current_admin.id}')
        return {'success': True}
    except Exception as e:
        logger.error(f'[POST /api/v1/admin/balance/deposit] Ошибка при пополнении баланса: {str(e)}')
        raise

@balance_router.post('/api/v1/admin/balance/withdraw', response_model=OkResponseSchema, tags=['admin', 'balance'])
async def withdraw_balance(
    balance_data: BalanceSchema,
    session: SessionDep,
    current_admin: UserModel = Depends(get_current_admin)
):
    logger.info(f'[POST /api/v1/admin/balance/withdraw] Админ {current_admin.id} инициировал списание баланса: user_id={balance_data.user_id}, ticker={balance_data.ticker}, amount={balance_data.amount}')
    
    try:
        user = await session.scalar(
            select(UserModel)
            .where(UserModel.id == balance_data.user_id)
        )
        
        if not user:
            logger.warning(f'[POST /api/v1/admin/balance/withdraw] Попытка списания баланса: пользователь {balance_data.user_id} не найден')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='User not found'
            )

        logger.info(f'[POST /api/v1/admin/balance/withdraw] Найден пользователь: id={user.id}')

        balance = await session.scalar(
            select(BalanceModel)
            .where(
                BalanceModel.user_id == balance_data.user_id,
                BalanceModel.ticker == balance_data.ticker
            )
        )
        
        if not balance:
            logger.warning(f'[POST /api/v1/admin/balance/withdraw] Попытка списания баланса: баланс по тикеру {balance_data.ticker} не найден у пользователя {balance_data.user_id}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'No balance found for ticker {balance_data.ticker}'
            )

        logger.info(f'[POST /api/v1/admin/balance/withdraw] Текущий баланс пользователя: user_id={balance_data.user_id}, ticker={balance_data.ticker}, current_amount={balance.amount}')

        if balance.amount < balance_data.amount:
            logger.warning(f'[POST /api/v1/admin/balance/withdraw] Недостаточно средств: user_id={balance_data.user_id}, ticker={balance_data.ticker}, current_amount={balance.amount}, requested_amount={balance_data.amount}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Insufficient balance for withdrawal'
            )

        old_amount = balance.amount
        balance.amount -= balance_data.amount
        await session.commit()
        logger.info(f'[POST /api/v1/admin/balance/withdraw] Успешное списание баланса: user_id={balance_data.user_id}, ticker={balance_data.ticker}, old_amount={old_amount}, new_amount={balance.amount}, admin_id={current_admin.id}')
        return {'success': True}
    except Exception as e:
        logger.error(f'[POST /api/v1/admin/balance/withdraw] Ошибка при списании баланса: {str(e)}')
        raise