from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.orders.models import OrderModel, StatusEnum, DirectionEnum
from src.orders.schemas import OrderBodySchema, CreateOrderResponseSchema, OrderResponseSchema, LimitOrderSchema, LimitOrderBodySchema, MarketOrderSchema, MarketOrderBodySchema, OrderBookListSchema
from src.users.dependencies import get_current_user
from src.users.models import UserModel
from src.instruments.models import InstrumentModel
from src.balance.models import BalanceModel
from src.transactions.models import TransactionModel


order_router = APIRouter()

async def check_balance(
    session: SessionDep, 
    user_id: UUID, 
    ticker: str, 
    required_amount: float
):
    balance = await session.scalar(
        select(BalanceModel)
        .where(BalanceModel.user_id == user_id)
        .where(BalanceModel.ticker == ticker)
    )
    if not balance or balance.amount < required_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance for {ticker}"
        )
    return True

async def update_balance(
    session: SessionDep, 
    user_id: UUID, 
    ticker: str, 
    delta: float
):
    balance = await session.scalar(
        select(BalanceModel)
        .where(BalanceModel.user_id == user_id)
        .where(BalanceModel.ticker == ticker)
    )
    if not balance:
        balance = BalanceModel(user_id=user_id, ticker=ticker, amount=0)
        session.add(balance)
    new_amount = balance.amount + delta
    if new_amount < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Negative balance not allowed for {ticker}"
        )
    balance.amount = new_amount

@order_router.post('/api/v1/order', response_model=CreateOrderResponseSchema, tags=['order'])
async def create_order(
    session: SessionDep,
    user_data: OrderBodySchema,
    current_user: UserModel = Depends(get_current_user)
):
    try:
        if isinstance(user_data, LimitOrderBodySchema):
            price = user_data.price
        else:
            price = None

        if user_data.direction == DirectionEnum.BUY and price is not None:
            await check_balance(session, current_user.id, 'RUB', user_data.qty * price)
        elif user_data.direction == DirectionEnum.SELL:
            await check_balance(session, current_user.id, user_data.ticker, user_data.qty)

        new_order = OrderModel(
            user_id=current_user.id,
            ticker=user_data.ticker,
            direction=user_data.direction,
            qty=user_data.qty,
            price=price
        )

        instrument = await session.scalar(
            select(InstrumentModel)
            .where(InstrumentModel.ticker == user_data.ticker)
        )
        if not instrument:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Instrument not found'
            )

        if user_data.direction == DirectionEnum.BUY:
            opposite_direction = DirectionEnum.SELL
            sorting_by = (OrderModel.price.asc(), OrderModel.timestamp.asc())
            price_condition = OrderModel.price <= new_order.price if new_order.price else True
        else:
            opposite_direction = DirectionEnum.BUY
            sorting_by = (OrderModel.price.desc(), OrderModel.timestamp.asc())
            price_condition = OrderModel.price >= new_order.price if new_order.price else True

        matching_orders = await session.execute(
            select(OrderModel)
            .where(OrderModel.ticker == user_data.ticker)
            .where(OrderModel.direction == opposite_direction)
            .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
            .where(price_condition)
            .order_by(*sorting_by)
            .with_for_update()
        )
        matching_orders = matching_orders.scalars().all()

        if price is None:
            available_qty = sum(order.qty - order.filled for order in matching_orders)
            if available_qty < new_order.qty:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient liquidity for market order"
                )

        total_filled = 0
        for matching_order in matching_orders:
            if total_filled >= new_order.qty:
                break

            remaining_qty = new_order.qty - total_filled
            match_qty = min(remaining_qty, matching_order.qty - matching_order.filled)
            if match_qty <= 0:
                continue

            transaction_price = matching_order.price
            if transaction_price is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Matching order has no price")

            if new_order.direction == DirectionEnum.BUY:
                await check_balance(session, current_user.id, 'RUB', match_qty * transaction_price)
                await check_balance(session, matching_order.user_id, new_order.ticker, match_qty)
            else:
                await check_balance(session, current_user.id, new_order.ticker, match_qty)
                await check_balance(session, matching_order.user_id, 'RUB', match_qty * transaction_price)

            transaction = TransactionModel(
                ticker=new_order.ticker,
                amount=match_qty,
                price=transaction_price,
                timestamp=datetime.now(timezone.utc),
                buyer_id=current_user.id if new_order.direction == DirectionEnum.BUY else matching_order.user_id,
                seller_id=matching_order.user_id if new_order.direction == DirectionEnum.BUY else current_user.id
            )
            session.add(transaction)

            matching_order.filled += match_qty
            if matching_order.filled == matching_order.qty:
                matching_order.status = StatusEnum.EXECUTED
            else:
                matching_order.status = StatusEnum.PARTIALLY_EXECUTED

            total_filled += match_qty

            buyer = current_user.id if new_order.direction == DirectionEnum.BUY else matching_order.user_id
            seller = matching_order.user_id if new_order.direction == DirectionEnum.BUY else current_user.id

            await update_balance(session, buyer, 'RUB', -match_qty * transaction_price)
            await update_balance(session, seller, 'RUB', match_qty * transaction_price)
            await update_balance(session, buyer, new_order.ticker, match_qty)
            await update_balance(session, seller, new_order.ticker, -match_qty)

        new_order.filled = total_filled
        if total_filled == new_order.qty:
            new_order.status = StatusEnum.EXECUTED
        elif total_filled > 0 and price is not None:
            new_order.status = StatusEnum.PARTIALLY_EXECUTED
        else:
            new_order.status = StatusEnum.NEW

        if price is not None or new_order.status == StatusEnum.EXECUTED:
            session.add(new_order)
        await session.commit()

        return CreateOrderResponseSchema(
            success=True,
            order_id=new_order.id,
            filled_qty=new_order.filled,
            status=new_order.status
        )
    except SQLAlchemyError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unexpected error: {str(e)}"
        )

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
                id=order.id,
                status=order.status,
                user_id=order.user_id,
                timestamp=order.timestamp,
                body=LimitOrderBodySchema(**body_data, price=order.price),
                filled=order.filled
            ))
        else:
            result.append(MarketOrderSchema(
                id=order.id,
                status=order.status,
                user_id=order.user_id,
                timestamp=order.timestamp,
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
    order.status = None
    await session.commit()
    return {'success': True}

@order_router.get('/api/v1/public/orderbook/{ticker}', response_model=OrderBookListSchema, tags=['public'])
async def get_order_book(
    session: SessionDep,
    ticker: str
):
    bid_orders = await session.execute(
        select(OrderModel.price, func.sum(OrderModel.qty))
        .where(OrderModel.status.in_([None, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.BUY)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.price != None)
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.desc())
    )
    ask_orders = await session.execute(
        select(OrderModel.price, func.sum(OrderModel.qty))
        .where(OrderModel.status.in_([None, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.SELL)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.price != None)
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.asc())
    )
    bid_levels = [{"price": price, "qty": qty} for price, qty in bid_orders]
    ask_levels = [{"price": price, "qty": qty} for price, qty in ask_orders]
    return OrderBookListSchema(
        bid_levels=bid_levels,
        ask_levels=ask_levels
    )