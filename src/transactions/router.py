from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select, desc

from src.database import SessionDep
from src.transactions.models import TransactionModel
from src.transactions.schemas import TransactionRescponseSchema
from src.instruments.models import InstrumentModel
from src.logger import logger


transaction_router = APIRouter()

@transaction_router.get('/api/v1/public/transactions/{ticker}', response_model=list[TransactionRescponseSchema], tags=['public'])
async def get_transaction_history(
    session: SessionDep,
    ticker: str,
    limit: int = 10
):
    try:
        logger.info(f'[GET /api/v1/public/transactions/{ticker}] Начало запроса истории транзакций: ticker={ticker}, limit={limit}')
        
        instrument = await session.scalar(
            select(InstrumentModel).where(InstrumentModel.ticker == ticker)
        )
        
        if not instrument:
            logger.warning(f'[GET /api/v1/public/transactions/{ticker}] Инструмент не найден: ticker={ticker}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Instrument not found'
            )
        
        logger.info(f'[GET /api/v1/public/transactions/{ticker}] Инструмент найден: id={instrument.id}, name={instrument.name}')
        
        transactions = await session.scalars(
            select(TransactionModel)
            .where(TransactionModel.ticker == ticker)
            .order_by(desc(TransactionModel.timestamp))
            .limit(limit)
        )
        
        result = transactions.all()
        logger.info(f'[GET /api/v1/public/transactions/{ticker}] Получено транзакций: {len(result)}')
        
        for transaction in result:
            logger.info(f'[GET /api/v1/public/transactions/{ticker}] Транзакция: id={transaction.id}, amount={transaction.amount}, price={transaction.price}, buyer_id={transaction.buyer_id}, seller_id={transaction.seller_id}, timestamp={transaction.timestamp}')
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'[GET /api/v1/public/transactions/{ticker}] Ошибка при получении истории транзакций: {str(e)}', exc_info=True)
        raise