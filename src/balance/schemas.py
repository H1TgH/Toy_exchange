from pydantic import BaseModel, Field, RootModel
from uuid import UUID


class BalanceSchema(BaseModel):
    user_id: UUID
    ticker: str
    amount: int = Field(gt=0)

class GetBalanceResponseSchema(RootModel[dict[str, int]]):
    pass