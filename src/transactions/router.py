from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select, desc

from src.database import SessionDep
from src.transactions.models import TransactionModel
from src.transactions.schemas import TransactionRescponseSchema
from src.instruments.models import InstrumentModel


transaction_router = APIRouter()

@transaction_router.get('/api/v1/public/transactions/{ticker}', response_model=list[TransactionRescponseSchema], tags=['public'])
async def get_transaction_history(
    session: SessionDep,
    ticker: str,
    limit: int = 10
):
    instrument = await session.scalar(
        select(InstrumentModel).where(InstrumentModel.ticker == ticker)
    )
    if not instrument:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found"
        )

    transactions = await session.scalars(
        select(TransactionModel)
        .where(TransactionModel.ticker == ticker)
        .order_by(desc(TransactionModel.timestamp))
        .limit(limit)
    )

    return transactions.all()