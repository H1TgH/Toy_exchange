from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.orders.models import OrderModel, StatusEnum, DirectionEnum
from src.orders.schemas import OrderBodySchema, CreateOrderResponseSchema, OrderResponseSchema, LimitOrderSchema, LimitOrderBodySchema, MarketOrderSchema, MarketOrderBodySchema, OrderBookListSchema, OrderLevel
from src.users.dependencies import get_current_user
from src.users.models import UserModel
from src.instruments.models import InstrumentModel
from src.balance.models import BalanceModel
from src.transactions.models import TransactionModel
from src.logger import logger

order_router = APIRouter()

async def update_balance(
    session: SessionDep, 
    user_id: UUID, 
    ticker: str, 
    delta_amount: int,
    delta_available: int = None
):
    logger.debug(f'[UPDATE_BALANCE] Обновление баланса: user_id={user_id}, ticker={ticker}, delta_amount={delta_amount}, delta_available={delta_available}')
    balance = await session.scalar(
        select(BalanceModel)
        .where(BalanceModel.user_id == user_id)
        .where(BalanceModel.ticker == ticker)
        .order_by(BalanceModel.user_id, BalanceModel.ticker)
        .with_for_update()
    )

    if not balance:
        logger.info(f'Баланс для {ticker} у пользователя {user_id} не найден, создаем новый')
        balance = BalanceModel(user_id=user_id, ticker=ticker, amount=0, available=0) 
        session.add(balance)
        await session.flush()
    new_amount = balance.amount + delta_amount
    new_available = balance.available + (delta_available if delta_available is not None else delta_amount)
    
    if new_amount < 0 or new_available < 0:
        logger.error(f'Попытка установить отрицательный баланс для {ticker} у пользователя {user_id}: amount={new_amount}, available={new_available}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Negative balance not allowed for {ticker}'
        )
    
    balance.amount = new_amount
    balance.available = new_available
    logger.debug(f'Баланс для {ticker} у пользователя {user_id} обновлен: amount={new_amount}, available={new_available}')

@order_router.post('/api/v1/order', response_model=CreateOrderResponseSchema, tags=['order'])
async def create_order(
    session: SessionDep,
    user_data: OrderBodySchema,
    current_user: UserModel = Depends(get_current_user)
):
    try:
        logger.info(f'[POST /api/v1/order] Начало создания ордера: user_id={current_user.id}, ticker={user_data.ticker}, direction={user_data.direction}, qty={user_data.qty}, price={getattr(user_data, "price", None)}')

        instrument = await session.scalar(
            select(InstrumentModel)
            .where(InstrumentModel.ticker == user_data.ticker)
        )
        if not instrument:
            logger.warning(f'[POST /api/v1/order] Инструмент не найден: ticker={user_data.ticker}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Instrument not found'
            )
        logger.info(f'[POST /api/v1/order] Инструмент найден: ticker={user_data.ticker}')

        price = user_data.price if isinstance(user_data, LimitOrderBodySchema) else None
        logger.info(f'[POST /api/v1/order] Тип ордера: {"LIMIT" if price else "MARKET"}, price={price}')

        if user_data.direction == DirectionEnum.BUY:
            balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == current_user.id)
                .where(BalanceModel.ticker == 'RUB')
                .with_for_update()
            )
            if not balance or balance.available < user_data.qty * price:
                logger.warning(f'[POST /api/v1/order] Недостаточно RUB: доступно={balance.available if balance else 0}, требуется={user_data.qty * price}')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Insufficient RUB balance'
                )
            balance.available -= user_data.qty * price
            logger.info(f'[POST /api/v1/order] Зарезервировано RUB: {user_data.qty * price}, новый доступный баланс: {balance.available}')
        else:
            balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == current_user.id)
                .where(BalanceModel.ticker == user_data.ticker)
                .with_for_update()
            )
            if not balance or balance.available < user_data.qty:
                logger.warning(f'[POST /api/v1/order] Недостаточно {user_data.ticker}: доступно={balance.available if balance else 0}, требуется={user_data.qty}')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f'Insufficient {user_data.ticker} balance'
                )
            balance.available -= user_data.qty
            logger.info(f'[POST /api/v1/order] Зарезервировано {user_data.ticker}: {user_data.qty}, новый доступный баланс: {balance.available}')

        if price is None:
            opposite_direction = DirectionEnum.SELL if user_data.direction == DirectionEnum.BUY else DirectionEnum.BUY
            price_condition = True
            available_qty = await session.scalar(
                select(func.sum(OrderModel.qty - OrderModel.filled))
                .where(OrderModel.ticker == user_data.ticker)
                .where(OrderModel.direction == opposite_direction)
                .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
                .where(price_condition)
            )
            available_qty = available_qty or 0
            logger.info(f'[POST /api/v1/order] Доступная ликвидность для рыночного ордера: {available_qty}')
            if available_qty < user_data.qty:
                logger.warning(f'[POST /api/v1/order] Недостаточная ликвидность: доступно={available_qty}, требуется={user_data.qty}')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Insufficient liquidity for market order'
                )

        new_order = OrderModel(
            user_id=current_user.id,
            ticker=user_data.ticker,
            direction=user_data.direction,
            qty=user_data.qty,
            price=price
        )
        session.add(new_order)
        await session.flush()
        logger.info(f'[POST /api/v1/order] Создан новый ордер: id={new_order.id}, direction={new_order.direction}, qty={new_order.qty}, price={new_order.price}')

        try:
            await match_orders(session, new_order)
        except Exception as e:
            logger.error(f'[POST /api/v1/order] Ошибка при исполнении ордера: {str(e)}', exc_info=True)
            if user_data.direction == DirectionEnum.BUY:
                balance.available += user_data.qty * price
            else:
                balance.available += user_data.qty
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Error executing order'
            )

        logger.info(f'[POST /api/v1/order] Ордер успешно создан: id={new_order.id}, filled={new_order.filled}, status={new_order.status}')
        return CreateOrderResponseSchema(
            success=True,
            order_id=new_order.id,
            filled_qty=new_order.filled,
            status=new_order.status
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'[POST /api/v1/order] Неожиданная ошибка: {str(e)}', exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Internal server error'
        )

@order_router.delete('/api/v1/order/{order_id}', response_model=OkResponseSchema, tags=['order'])
async def cancel_order(
    session: SessionDep,
    order_id: UUID,
    current_user: UserModel = Depends(get_current_user)
):
    logger.info(f'[DELETE /api/v1/order/{order_id}] Запрос на отмену ордера: order_id={order_id}, user_id={current_user.id}')
    
    order = await session.scalar(
        select(OrderModel)
        .where(OrderModel.id == order_id)
        .with_for_update()
    )
    if not order:
        logger.warning(f'[DELETE /api/v1/order/{order_id}] Ордер не найден: order_id={order_id}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Order not found'
        )
    if order.user_id != current_user.id:
        logger.warning(f'[DELETE /api/v1/order/{order_id}] Попытка отменить чужой ордер: order_id={order_id}, user_id={current_user.id}, owner_id={order.user_id}')
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='You can only cancel your own orders'
        )
    
    if order.status in [StatusEnum.EXECUTED, StatusEnum.CANCELLED]:
        logger.warning(f'[DELETE /api/v1/order/{order_id}] Невозможно отменить исполненный или отмененный ордер: order_id={order_id}, status={order.status}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cannot cancel executed or cancelled order.'
        )
    
    if not order.price:
        logger.warning(f'[DELETE /api/v1/order/{order_id}] Невозможно отменить рыночный ордер: order_id={order_id}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cannot cancel market order'
        )
    
    logger.info(f'[DELETE /api/v1/order/{order_id}] Получение балансов для отмены: user_id={current_user.id}, ticker={order.ticker}')
    if order.direction == DirectionEnum.BUY:
        await update_balance(session, current_user.id, 'RUB', 0, (order.qty - order.filled) * order.price)
        logger.info(f'[DELETE /api/v1/order/{order_id}] Возвращены RUB: amount={(order.qty - order.filled) * order.price}')
    else:
        await update_balance(session, current_user.id, order.ticker, 0, order.qty - order.filled)
        logger.info(f'[DELETE /api/v1/order/{order_id}] Возвращен {order.ticker}: amount={order.qty - order.filled}')
    
    order.status = StatusEnum.CANCELLED 
    logger.info(f'[DELETE /api/v1/order/{order_id}] Ордер успешно отменен: order_id={order_id}')
    return {'success': True}

@order_router.get('/api/v1/order', response_model=list[OrderResponseSchema], tags=['order'])
async def get_orders_list(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user)
):
    logger.info(f'[GET /api/v1/order] Запрос списка ордеров: user_id={current_user.id}')
    orders = await session.scalars(
        select(OrderModel)
        .where(OrderModel.user_id == current_user.id)
    )
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
            logger.info(f'[GET /api/v1/order] Лимитный ордер: id={order.id}, direction={order.direction}, qty={order.qty}, filled={order.filled}, price={order.price}')
        else:
            result.append(MarketOrderSchema(
                id=order.id,
                status=order.status,
                user_id=order.user_id,
                timestamp=order.timestamp,
                body=MarketOrderBodySchema(**body_data)
            ))
            logger.info(f'[GET /api/v1/order] Рыночный ордер: id={order.id}, direction={order.direction}, qty={order.qty}, filled={order.filled}')

    logger.info(f'[GET /api/v1/order] Возвращено ордеров: {len(result)}')
    return result

@order_router.get('/api/v1/order/{order_id}', response_model=OrderResponseSchema, tags=['order'])
async def get_order(
    session: SessionDep,
    order_id: UUID,
    current_user: UserModel = Depends(get_current_user)
):
    logger.info(f'[GET /api/v1/order/{order_id}] Запрос ордера: order_id={order_id}, user_id={current_user.id}')
    order = await session.scalar(
        select(OrderModel)
        .where(OrderModel.id == order_id)
    )
    if not order:
        logger.warning(f'[GET /api/v1/order/{order_id}] Ордер не найден: order_id={order_id}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Order not found'
        )
    body_data = {
        'direction': order.direction,
        'ticker': order.ticker,
        'qty': order.qty
    }
    logger.info(f'[GET /api/v1/order/{order_id}] Информация об ордере: id={order.id}, direction={order.direction}, qty={order.qty}, filled={order.filled}, price={order.price}')
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

@order_router.get('/api/v1/public/orderbook/{ticker}', response_model=OrderBookListSchema, tags=['public'])
async def get_order_book(
    session: SessionDep,
    ticker: str
):
    logger.info(f'[GET /api/v1/public/orderbook/{ticker}] Запрос стакана: ticker={ticker}')
    bid_orders = await session.execute(
        select(
            OrderModel.price,
            func.sum(OrderModel.qty - OrderModel.filled)
        )
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.BUY)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.price != None)
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.desc())
    )

    ask_orders = await session.execute(
        select(
            OrderModel.price,
            func.sum(OrderModel.qty - OrderModel.filled)
        )
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.SELL)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.price != None)
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.asc())
    )

    bid_levels = [OrderLevel(price=price, qty=qty) for price, qty in bid_orders if qty > 0]
    ask_levels = [OrderLevel(price=price, qty=qty) for price, qty in ask_orders if qty > 0]
    
    logger.info(f'[GET /api/v1/public/orderbook/{ticker}] Стакан {ticker}:')
    logger.info(f'[GET /api/v1/public/orderbook/{ticker}] Бид уровни: {bid_levels}')
    logger.info(f'[GET /api/v1/public/orderbook/{ticker}] Аск уровни: {ask_levels}')
    
    return OrderBookListSchema(
        bid_levels=bid_levels,
        ask_levels=ask_levels
    )

async def match_orders(session: SessionDep, new_order: OrderModel):
    logger.info(f'[match_orders] Начало исполнения ордера: id={new_order.id}, direction={new_order.direction}, qty={new_order.qty}, price={new_order.price}')

    opposite_direction = DirectionEnum.SELL if new_order.direction == DirectionEnum.BUY else DirectionEnum.BUY
    sorting_by = (OrderModel.price.asc(), OrderModel.timestamp.asc()) if new_order.direction == DirectionEnum.BUY else (OrderModel.price.desc(), OrderModel.timestamp.asc())
    price_condition = (OrderModel.price <= new_order.price if new_order.price and new_order.direction == DirectionEnum.BUY else
                          OrderModel.price >= new_order.price if new_order.price else True)

    matching_orders = await session.scalars(
        select(OrderModel)
        .where(OrderModel.ticker == new_order.ticker)
        .where(OrderModel.direction == opposite_direction)
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(price_condition)
        .order_by(OrderModel.user_id, OrderModel.ticker, *sorting_by)
        .with_for_update()
    )
    matching_orders = list(matching_orders)
    logger.info(f'[match_orders] Найдено подходящих ордеров: {len(matching_orders)}')

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
            logger.error(f'[match_orders] Совпадающий ордер не имеет цены: id={matching_order.id}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Matching order has no price'
            )

        buyer = new_order.user_id if new_order.direction == DirectionEnum.BUY else matching_order.user_id
        seller = matching_order.user_id if new_order.direction == DirectionEnum.BUY else new_order.user_id
        logger.info(f'[match_orders] Исполнение сделки: buyer={buyer}, seller={seller}, qty={match_qty}, price={transaction_price}')

        if buyer == seller:
            logger.info(f'[match_orders] Самоторговля: buyer={buyer}, seller={seller}, qty={match_qty}, price={transaction_price}. Пропускаем обновление балансов.')
        else:
            buyer_rub_balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == buyer)
                .where(BalanceModel.ticker == 'RUB')
                .with_for_update()
            )
            if not buyer_rub_balance:
                buyer_rub_balance = BalanceModel(user_id=buyer, ticker='RUB', amount=0, available=0)
                session.add(buyer_rub_balance)

            buyer_ticker_balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == buyer)
                .where(BalanceModel.ticker == new_order.ticker)
                .with_for_update()
            )
            if not buyer_ticker_balance:
                buyer_ticker_balance = BalanceModel(user_id=buyer, ticker=new_order.ticker, amount=0, available=0)
                session.add(buyer_ticker_balance)

            seller_rub_balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == seller)
                .where(BalanceModel.ticker == 'RUB')
                .with_for_update()
            )
            if not seller_rub_balance:
                seller_rub_balance = BalanceModel(user_id=seller, ticker='RUB', amount=0, available=0)
                session.add(seller_rub_balance)

            seller_ticker_balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == seller)
                .where(BalanceModel.ticker == new_order.ticker)
                .with_for_update()
            )
            if not seller_ticker_balance:
                seller_ticker_balance = BalanceModel(user_id=seller, ticker=new_order.ticker, amount=0, available=0)
                session.add(seller_ticker_balance)

            buyer_rub_balance.amount -= match_qty * transaction_price
            buyer_ticker_balance.amount += match_qty
            seller_rub_balance.amount += match_qty * transaction_price
            seller_ticker_balance.amount -= match_qty

            if new_order.direction == DirectionEnum.BUY:
                buyer_rub_balance.available = buyer_rub_balance.amount + (new_order.qty - total_filled - match_qty) * new_order.price
                seller_ticker_balance.available = seller_ticker_balance.amount + (matching_order.qty - matching_order.filled - match_qty)
            else:
                seller_rub_balance.available = seller_rub_balance.amount + (new_order.qty - total_filled - match_qty) * new_order.price
                buyer_ticker_balance.available = buyer_ticker_balance.amount + (matching_order.qty - matching_order.filled - match_qty)

            logger.info(f'[match_orders] Обновлены балансы:')
            logger.info(f'[match_orders] Покупатель RUB: amount={buyer_rub_balance.amount}, available={buyer_rub_balance.available}')
            logger.info(f'[match_orders] Покупатель {new_order.ticker}: amount={buyer_ticker_balance.amount}, available={buyer_ticker_balance.available}')
            logger.info(f'[match_orders] Продавец RUB: amount={seller_rub_balance.amount}, available={seller_rub_balance.available}')
            logger.info(f'[match_orders] Продавец {new_order.ticker}: amount={seller_ticker_balance.amount}, available={seller_ticker_balance.available}')

        matching_order.filled += match_qty
        if matching_order.filled == matching_order.qty:
            matching_order.status = StatusEnum.EXECUTED
            logger.info(f'[match_orders] Ордер полностью исполнен: id={matching_order.id}')
        else:
            matching_order.status = StatusEnum.PARTIALLY_EXECUTED
            logger.info(f'[match_orders] Ордер частично исполнен: id={matching_order.id}, filled={matching_order.filled}')

        total_filled += match_qty
        logger.info(f'[match_orders] Текущий прогресс исполнения: total_filled={total_filled}')

        if buyer != seller:
            transaction = TransactionModel(
                ticker=new_order.ticker,
                amount=match_qty,
                price=transaction_price,
                timestamp=datetime.now(timezone.utc),
                buyer_id=buyer,
                seller_id=seller
            )
            session.add(transaction)
            await session.flush()
            logger.info(f'[match_orders] Создана транзакция: id={transaction.id}, ticker={transaction.ticker}, amount={transaction.amount}, price={transaction.price}')

    new_order.filled = total_filled
    if total_filled == new_order.qty:
        new_order.status = StatusEnum.EXECUTED
        logger.info(f'[match_orders] Новый ордер полностью исполнен: id={new_order.id}')
    elif total_filled > 0:
        new_order.status = StatusEnum.PARTIALLY_EXECUTED
        logger.info(f'[match_orders] Новый ордер частично исполнен: id={new_order.id}, filled={total_filled}')
    else:
        new_order.status = StatusEnum.NEW
        logger.info(f'[match_orders] Новый ордер создан: id={new_order.id}')

    await session.commit()
    logger.info(f'[match_orders] Исполнение ордера завершено: id={new_order.id}, filled={new_order.filled}, status={new_order.status}')