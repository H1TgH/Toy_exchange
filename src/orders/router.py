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
from src.logger import logger

order_router = APIRouter()

async def check_balance(
    session: SessionDep, 
    user_id: UUID, 
    ticker: str, 
    required_amount: int
):
    logger.debug(f'Проверка баланса: user_id={user_id}, ticker={ticker}, required_amount={required_amount}')
    balance = await session.scalar(
        select(BalanceModel)
        .where(BalanceModel.user_id == user_id)
        .where(BalanceModel.ticker == ticker)
    )
    if not balance or balance.amount < required_amount:
        logger.warning(f'Недостаточный баланс для {ticker} у пользователя {user_id}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Insufficient balance for {ticker}'
        )
    return True

async def update_balance(
    session: SessionDep, 
    user_id: UUID, 
    ticker: str, 
    delta: float
):
    logger.debug(f'Обновление баланса: user_id={user_id}, ticker={ticker}, delta={delta}')
    balance = await session.scalar(
        select(BalanceModel)
        .where(BalanceModel.user_id == user_id)
        .where(BalanceModel.ticker == ticker)
    )
    if not balance:
        logger.info(f'Баланс для {ticker} у пользователя {user_id} не найден, создаем новый с 0')
        balance = BalanceModel(user_id=user_id, ticker=ticker, amount=0)
        session.add(balance)
    new_amount = balance.amount + delta
    if new_amount < 0:
        logger.error(f'Попытка установить отрицательный баланс для {ticker} у пользователя {user_id}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Negative balance not allowed for {ticker}'
        )
    balance.amount = new_amount
    logger.debug(f'Баланс для {ticker} у пользователя {user_id} обновлен: {new_amount}')

@order_router.post('/api/v1/order', response_model=CreateOrderResponseSchema, tags=['order'])
async def create_order(
    session: SessionDep,
    user_data: OrderBodySchema,
    current_user: UserModel = Depends(get_current_user)
):
    logger.info(f'Создание ордера: user_id={current_user.id}, ticker={user_data.ticker}, direction={user_data.direction}, qty={user_data.qty}, price={getattr(user_data, 'price', None)}')

    if isinstance(user_data, LimitOrderBodySchema):
        price = user_data.price
    else:
        price = None

    try:
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
            logger.warning(f'Инструмент с тикером {user_data.ticker} не найден при создании ордера')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
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

        matching_orders_result = await session.execute(
            select(OrderModel)
            .where(OrderModel.ticker == user_data.ticker)
            .where(OrderModel.direction == opposite_direction)
            .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
            .where(price_condition)
            .order_by(*sorting_by)
            .with_for_update()
        )
        matching_orders = matching_orders_result.scalars().all()

        logger.debug(f'Найдено {len(matching_orders)} подходящих ордеров для матчмейкинга')

        if price is None:
            available_qty = sum(order.qty - order.filled for order in matching_orders)
            if available_qty < new_order.qty:
                logger.warning('Недостаточная ликвидность для рыночного ордера')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Insufficient liquidity for market order'
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
                logger.error('Совпадающий ордер не имеет цены')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Matching order has no price'
                )

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

        logger.info(f'Ордер создан: id={new_order.id}, filled={new_order.filled}, status={new_order.status}')
        return CreateOrderResponseSchema(
            success=True,
            order_id=new_order.id,
            filled_qty=new_order.filled,
            status=new_order.status
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'Ошибка при создании ордера: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail='Internal Server Error')

@order_router.get('/api/v1/order', response_model=list[OrderResponseSchema], tags=['order'])
async def get_orders_list(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user)
):
    logger.info(f'Запрос списка ордеров пользователем {current_user.id}')
    orders = await session.scalars(select(OrderModel))
    result = []
    for order in orders:
        body_data = {
            'direction': order.direction,
            'ticker': order.ticker,
            'qty': order.qty,
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
    logger.info(f'Возвращено {len(result)} ордеров')
    return result

@order_router.get('/api/v1/order/{order_id}', response_model=OrderResponseSchema, tags=['order'])
async def get_order(
    session: SessionDep,
    order_id: UUID,
    current_user: UserModel = Depends(get_current_user)
):
    logger.info(f'Запрос ордера id={order_id} пользователем {current_user.id}')
    order = await session.scalar(select(OrderModel).where(OrderModel.id == order_id))
    if not order:
        logger.warning(f'Ордер с id={order_id} не найден')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
    logger.info(f'Запрос на отмену ордера id={order_id} пользователем {current_user.id}')
    order = await session.scalar(
        select(OrderModel)
        .where(OrderModel.id == order_id)
    )
    if not order:
        logger.warning(f'Ордер с id={order_id} не найден для отмены')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Order not found'
        )
    if order.user_id != current_user.id:
        logger.warning(f'Невозможно отменить ордер id={order_id} другому пользователю')
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='You can only cancel your own orders'
        )
    
    if order.status in [StatusEnum.PARTIALLY_EXECUTED, StatusEnum.EXECUTED]:
        logger.warning(f'Невозможно отменить ордер id={order_id} со статусом {order.status}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cannot cancel executed or partially executed order.'
        )
    
    if not order.price:
        logger.warning(f'Невозможно отменить рыночный ордер id={order_id}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cannot cancel market order'
        )
    
    order.status = StatusEnum.CANCELLED 
    await session.commit()
    logger.info(f'Ордер id={order_id} отменен')
    return {'success': True}

@order_router.get('/api/v1/public/orderbook/{ticker}', response_model=OrderBookListSchema, tags=['public'])
async def get_order_book(
    session: SessionDep,
    ticker: str
):
    logger.info(f'Запрос стакана по тикеру {ticker}')
    bid_levels = await session.execute(
        select(OrderModel)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.direction == DirectionEnum.BUY)
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .order_by(OrderModel.price.desc())
    )
    ask_levels = await session.execute(
        select(OrderModel)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.direction == DirectionEnum.SELL)
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .order_by(OrderModel.price.asc())
    )
    bids = bid_levels.scalars().all()
    asks = ask_levels.scalars().all()
    logger.info(f'Получено {len(bids)} бидов и {len(asks)} асков для стакана {ticker}')

    return OrderBookListSchema(
        bid_levels=bid_levels,
        ask_levels=ask_levels
    )