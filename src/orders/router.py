from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.orders.models import OrderModel
from src.orders.schemas import  OrderBodySchema, CreateOrderResponseSchema, OrderResponseSchema, LimitOrderSchema, LimitOrderBodySchema, MarketOrderSchema, MarketOrderBodySchema
from src.users.dependencies import get_current_user
from src.users.models import UserModel


order_router = APIRouter()

@order_router.post('/api/v1/order', response_model=CreateOrderResponseSchema,tags=['order'])
async def create_order(
    session: SessionDep,
    user_data: OrderBodySchema,
    current_user: UserModel = Depends(get_current_user)
):
    new_order = OrderModel(
        user_id = current_user.id,
        ticker = user_data.ticker,
        direction = user_data.direction,
        qty = user_data.qty,
        price = user_data.price,
    )

    session.add(new_order)
    await session.commit()

    return {
        'success': True,
        'order_id': new_order.id
    }

@order_router.get('/api/v1/order/{order_id}', response_model=OrderResponseSchema, tags=['order'])
async def get_order(
    session: SessionDep,
    order_id: UUID,
    current_user: UserModel = Depends(get_current_user)
):
    order = await session.scalar(
        select(OrderModel).where(OrderModel.id == order_id, OrderModel.user_id == current_user.id)
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Order not found'
        )

    body_data = {
        "direction": order.direction,
        "ticker": order.ticker,
        "qty": order.qty
    }

    if order.price is not None:
        return LimitOrderSchema(
            id=order.id,
            user_id=order.user_id,
            status=order.status,
            timestamp=order.timestamp,
            filled=order.filled,
            body=LimitOrderBodySchema(**body_data, price=order.price)
        )
    else:
        return MarketOrderSchema(
            id=order.id,
            user_id=order.user_id,
            status=order.status,
            timestamp=order.timestamp,
            body=MarketOrderBodySchema(**body_data)
        )