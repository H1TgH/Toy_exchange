from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class BalanceSchema(BaseModel):
    user_id: UUID
    ticker: str
    amount: int = Field(gt=0)

class GetBalanceResponceSchema(BaseModel):
    __root__: dict[str, int]