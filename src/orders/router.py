from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update, func

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.orders.models import OrderModel, StatusEnum, DirectionEnum
from src.orders.schemas import  OrderBodySchema, CreateOrderResponseSchema, OrderResponseSchema, LimitOrderSchema, LimitOrderBodySchema, MarketOrderSchema, MarketOrderBodySchema, OrderBookListSchema
from src.users.dependencies import get_current_user
from src.users.models import UserModel
from src.instruments.models import InstrumentModel
from src.balance.models import BalanceModel
from src.transactions.models import TransactionModel


order_router = APIRouter()

@order_router.post('/api/v1/order', response_model=OkResponseSchema, tags=['order'])
async def create_order(
    session: SessionDep,
    user_data: OrderBodySchema,
    current_user: UserModel = Depends(get_current_user)
):
    new_order = OrderModel(
        user_id = current_user.id,
        ticker = user_data.ticker,
        direction = user_data.direction,
        qty = user_data.qty
    )

    if user_data.price is not None:
        new_order.price = user_data.price
    

    instrument = await session.scalar(
        select(InstrumentModel)
        .where(InstrumentModel.ticker == user_data.ticker)
    )

    if not instrument:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Instrument not found'
        )

    if user_data.direction == DirectionEnum.BUY and user_data.price is not None:
        balance = await session.scalar(
            select(BalanceModel)
            .where(BalanceModel.user_id == current_user.id)
            .where(BalanceModel.ticker == 'RUB')
        )
        if not balance or balance.amount < (user_data.qty * user_data.price):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Not enough money in the balance'
            )
    if user_data.direction == DirectionEnum.SELL:
        balance = await session.scalar(
            select(BalanceModel)
            .where(BalanceModel.user_id == current_user.id)
            .where(BalanceModel.ticker == user_data.ticker)
        )
        if not balance or balance.amount < user_data.qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient {user_data.ticker} balance"
            )
    
    if user_data.direction == DirectionEnum.BUY:
        opposite_direction = DirectionEnum.SELL
        sorting_by = OrderModel.price.asc()
        if new_order.price:
            price_condition = OrderModel.price <= new_order.price
        else:
            price_condition = True
    else:
        opposite_direction = DirectionEnum.BUY
        sorting_by = OrderModel.price.desc()
        if new_order.price:
            price_condition = OrderModel.price >= new_order.price
        else:
            price_condition = True

    matching_orders = await session.execute(
        select(OrderModel)
        .where(OrderModel.ticker == user_data.ticker)
        .where(OrderModel.direction == opposite_direction)
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(price_condition)
        .order_by(sorting_by)
        .with_for_update()
    )
    matching_orders = matching_orders.scalars().all()

    total_filled = 0
    for matching_order in matching_orders:
        if total_filled >= new_order.qty:
            break

        remaining_qty = new_order.qty - total_filled
        match_qty = min(remaining_qty, matching_order.qty - matching_order.filled)

        total_filled += match_qty
        matching_order.filled += match_qty

        if matching_order.filled == matching_order.qty:
            matching_order.status = StatusEnum.EXECUTED
        else:
            matching_order.status = StatusEnum.PARTIALLY_EXECUTED

    new_order.filled = total_filled
    if total_filled == new_order.qty:
        new_order.status = StatusEnum.EXECUTED
    elif total_filled > 0:
        new_order.status = StatusEnum.PARTIALLY_EXECUTED
    else:
        new_order.status = StatusEnum.NEW

    for matching_order in matching_orders:
        match_qty = min(new_order.qty - total_filled, matching_order.qty - matching_order.filled)
        if match_qty > 0:
            transaction_price = matching_order.price if matching_order.price else new_order.price
            transaction = TransactionModel(
                ticker=new_order.ticker,
                amount=match_qty,
                price=transaction_price,
                timestamp=datetime.now(timezone.utc)
            )
            session.add(transaction)

            # Обновление балансов
            buyer = current_user if new_order.direction == DirectionEnum.BUY else matching_order.user
            seller = matching_order.user if new_order.direction == DirectionEnum.BUY else current_user

            # Списываем RUB у покупателя
            buyer_balance_rub = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == buyer.id)
                .where(BalanceModel.ticker == 'RUB')
            )
            if not buyer_balance_rub:
                buyer_balance_rub = BalanceModel(user_id=buyer.id, ticker='RUB', amount=0)
                session.add(buyer_balance_rub)
            buyer_balance_rub.amount -= match_qty * transaction_price

            # Зачисляем RUB продавцу
            seller_balance_rub = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == seller.id)
                .where(BalanceModel.ticker == 'RUB')
            )
            if not seller_balance_rub:
                seller_balance_rub = BalanceModel(user_id=seller.id, ticker='RUB', amount=0)
                session.add(seller_balance_rub)
            seller_balance_rub.amount += match_qty * transaction_price

            # Списываем тикер у продавца
            seller_balance_ticker = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == seller.id)
                .where(BalanceModel.ticker == new_order.ticker)
            )
            if not seller_balance_ticker:
                seller_balance_ticker = BalanceModel(user_id=seller.id, ticker=new_order.ticker, amount=0)
                session.add(seller_balance_ticker)
            seller_balance_ticker.amount -= match_qty

            # Зачисляем тикер покупателю
            buyer_balance_ticker = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == buyer.id)
                .where(BalanceModel.ticker == new_order.ticker)
            )
            if not buyer_balance_ticker:
                buyer_balance_ticker = BalanceModel(user_id=buyer.id, ticker=new_order.ticker, amount=0)
                session.add(buyer_balance_ticker)
            buyer_balance_ticker.amount += match_qty

    # Фиксация изменений
    session.add(new_order)
    await session.commit()

    return {
        "success": True,
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
        .where(OrderModel.price.isnot(None))
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.desc())
    )
    ask_orders = await session.execute(
        select(OrderModel.price, func.sum(OrderModel.qty))
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.SELL)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.price.isnot(None))
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.asc())
    )

    bid_levels = [{"price": price, "qty": qty} for price, qty in bid_orders]
    ask_levels = [{"price": price, "qty": qty} for price, qty in ask_orders]

    return OrderBookListSchema(
        bid_levels=bid_levels,
        ask_levels=ask_levels
    )