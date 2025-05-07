from typing import Union, Literal
from pydantic import BaseModel, Field
from datetime import datetime

from src.orders.models import DirectionEnum, StatusEnum

class MarketOrderBodySchema(BaseModel):
    direction: DirectionEnum
    ticker: str
    qty: int = Field(ge=1)

class LimitOrderBodySchema(MarketOrderBodySchema):
    price: int = Field(gt=0)

class OrderSchema(BaseModel):
    id: str
    status: StatusEnum
    user_id: str
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
    order_id: str
