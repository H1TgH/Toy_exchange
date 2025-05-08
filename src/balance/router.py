from fastapi import APIRouter, HTTPException, Depends, status
from uuid import UUID
from sqlalchemy import select, update
from datetime import datetime

from src.database import SessionDep
from src.balance.models import BalanceModel
from src.transactions.models import TransactionModel
from src.users.models import UserModel
from src.balance.schemas import BalanceSchema
from src.users.dependencies import get_current_admin
from src.schemas import OkResponseSchema


balance_router = APIRouter()

@balance_router.post('/api/v1/admin/balance/deposit', response_model=OkResponseSchema)
async def replenish_balance(
    balance_data: BalanceSchema, 
    session: SessionDep,
    current_admin: UserModel = Depends(get_current_admin)
):
    if balance_data.user_id != current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only replenish your own balance"
        )
    
    balance = await session.scalar(
        select(BalanceModel).where(BalanceModel.user_id == balance_data.user_id, BalanceModel.ticker == balance_data.ticker)
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
    
    transaction = TransactionModel(
        buyer_id=balance_data.user_id,
        ticker=balance_data.ticker,
        amount=balance_data.amount,
        price=0,
        timestamp=datetime.utcnow(),
    )
    session.add(transaction)
    
    await session.commit()
    
    return {'success': True}
