from uuid import UUID
from datetime import datetime

from pydantic import BaseModel


class TransactionRescponseSchema(BaseModel):
    ticker: str
    amount: int
    price: int
    timestamp: datetime