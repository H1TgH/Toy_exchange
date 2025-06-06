from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class TransactionSchema(BaseModel):
    id: UUID
    buyer_id: UUID | None
    seller_id: UUID | None
    ticker: str
    amount: int
    price: int
    timestamp: datetime