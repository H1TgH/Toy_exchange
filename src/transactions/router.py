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
    logger.info(f'Запрос истории транзакций по инструменту {ticker} с лимитом {limit}')
    
    instrument = await session.scalar(
        select(InstrumentModel).where(InstrumentModel.ticker == ticker)
    )
    if not instrument:
        logger.warning(f'Инструмент с тикером {ticker} не найден при запросе истории транзакций')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Instrument not found'
        )

    transactions = await session.scalars(
        select(TransactionModel)
        .where(TransactionModel.ticker == ticker)
        .order_by(desc(TransactionModel.timestamp))
        .limit(limit)
    )
    
    result = transactions.all()
    logger.info(f'Возвращено {len(result)} транзакций для инструмента {ticker}')
    return result