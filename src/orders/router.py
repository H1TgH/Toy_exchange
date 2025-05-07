from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update, func

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.orders.models import OrderModel, StatusEnum, DirectionEnum
from src.orders.schemas import  OrderBodySchema, CreateOrderResponseSchema, OrderResponseSchema, LimitOrderSchema, LimitOrderBodySchema, MarketOrderSchema, MarketOrderBodySchema, OrderBookListSchema
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

@order_router.get('/api/v1/order', response_model=list[OrderResponseSchema], tags=['order'])
async def get_orders_list(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user)
):
    orders = await session.scalars(select(OrderModel))

    result = []
    for order in orders:
        body_data = {
            "direction": order.direction,
            "ticker": order.ticker,
            "qty": order.qty,
        }

        if order.price is not None:
            result.append(LimitOrderSchema(
                id = order.id,
                status = order.status,
                user_id = order.user_id,
                timestamp = order.timestamp,
                body=LimitOrderBodySchema(**body_data, price=order.price),
                filled=order.filled
            ))
        else:
            result.append(MarketOrderSchema(
                id = order.id,
                status = order.status,
                user_id = order.user_id,
                timestamp = order.timestamp,
                body=MarketOrderBodySchema(**body_data)
            ))

    return result

@order_router.get('/api/v1/order/{order_id}', response_model=OrderResponseSchema, tags=['order'])
async def get_order(
    session: SessionDep,
    order_id: UUID,
    current_user: UserModel = Depends(get_current_user)
):
    order = await session.scalar(
        select(OrderModel).where(OrderModel.id == order_id)
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Order not found'
        )

    body_data = {
        'direction': order.direction,
        'ticker': order.ticker,
        'qty': order.qty
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
    
@order_router.delete('/api/v1/order/{order_id}', response_model=OkResponseSchema, tags=['order'])
async def cancel_order(
    session: SessionDep,
    order_id: UUID,
    current_user: UserModel = Depends(get_current_user)
):
    order = await session.scalar(
        select(OrderModel).where(OrderModel.id == order_id)
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Order not found'
        )
    
    if order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='You can only cancel your own orders'
        )
    
    order.status = StatusEnum.CANCELLED

    await session.commit()

    return {'success': True}

@order_router.get('/api/v1/public/orderbook/{ticker}', response_model=OrderBookListSchema, tags=['public'])
async def get_order_book(
    session: SessionDep,
    ticker: str
):
    bid_orders = await session.execute(
        select(OrderModel.price, func.sum(OrderModel.qty))
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.BUY)
        .where(OrderModel.ticker == ticker)
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.desc())
    )
    ask_orders = await session.execute(
        select(OrderModel.price, func.sum(OrderModel.qty))
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.SELL)
        .where(OrderModel.ticker == ticker)
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.asc())
    )

    bid_levels = [{"price": price, "qty": qty} for price, qty in bid_orders]
    ask_levels = [{"price": price, "qty": qty} for price, qty in ask_orders]

    return OrderBookListSchema(
        bid_levels=bid_levels,
        ask_levels=ask_levels
    )