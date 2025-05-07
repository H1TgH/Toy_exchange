from typing import Union, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import List

from src.orders.models import DirectionEnum, StatusEnum

class MarketOrderBodySchema(BaseModel):
    direction: DirectionEnum
    ticker: str
    qty: int = Field(ge=1)

class LimitOrderBodySchema(MarketOrderBodySchema):
    price: int = Field(gt=0)

class OrderSchema(BaseModel):
    id: UUID
    status: StatusEnum
    user_id: UUID
    timestamp: datetime

class LimitOrderSchema(OrderSchema):
    body: LimitOrderBodySchema
    filled: int = Field(default=0)

class MarketOrderSchema(OrderSchema):
    body: MarketOrderBodySchema

OrderBodySchema = Union[LimitOrderBodySchema, MarketOrderBodySchema]

OrderResponseSchema = Union[LimitOrderSchema, MarketOrderSchema]

class CreateOrderResponseSchema(BaseModel):
    success: Literal[True] = Field(default=True)
    order_id: UUID

class OrderLevel(BaseModel):
    price: int
    qty: int

class OrderBookListSchema(BaseModel):
    bid_levels: List[OrderLevel]
    ask_levels: List[OrderLevel]