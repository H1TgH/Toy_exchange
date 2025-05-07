from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.orders.models import OrderModel
from src.orders.schemas import  OrderBodySchema, CreateOrderResponseSchema 
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