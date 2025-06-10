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
    required_amount: int,
    reserve_amount: int = 0
):
    logger.debug(f'Проверка баланса: user_id={user_id}, ticker={ticker}, требуется={required_amount}, резервировать={reserve_amount}')
    balance = await session.scalar(
        select(BalanceModel)
        .where(BalanceModel.user_id == user_id)
        .where(BalanceModel.ticker == ticker)
    )
    if not balance or balance.available < required_amount:
        logger.warning(f'Недостаточный доступный баланс для {ticker} у пользователя {user_id}: доступно={balance.available if balance else 0}, требуется={required_amount}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Insufficient balance for {ticker}'
        )
    
    if reserve_amount > 0:
        balance.available -= reserve_amount
        logger.debug(f'Зарезервировано {reserve_amount} {ticker} для пользователя {user_id}, новый доступный баланс: {balance.available}')
    
    return balance

async def update_balance(
    session: SessionDep, 
    user_id: UUID, 
    ticker: str, 
    delta_amount: float,
    delta_available: float = None
):
    logger.debug(f'Обновление баланса: user_id={user_id}, ticker={ticker}, delta_amount={delta_amount}, delta_available={delta_available}')
    balance = await session.scalar(
        select(BalanceModel)
        .where(BalanceModel.user_id == user_id)
        .where(BalanceModel.ticker == ticker)
    )

    if not balance:
        logger.info(f'Баланс для {ticker} у пользователя {user_id} не найден, создаем новый')
        balance = BalanceModel(user_id=user_id, ticker=ticker, amount=0, available=0)
        session.add(balance)

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
        logger.info(f'Создание ордера: user_id={current_user.id}, ticker={user_data.ticker}, direction={user_data.direction}, qty={user_data.qty}, price={getattr(user_data, "price", None)}')
        
        if user_data.direction == DirectionEnum.BUY:
            balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == current_user.id)
                .where(BalanceModel.ticker == 'RUB')
                .with_for_update()
            )
        else:
            balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == current_user.id)
                .where(BalanceModel.ticker == user_data.ticker)
                .with_for_update()
            )

        if isinstance(user_data, LimitOrderBodySchema):
            price = user_data.price
        else:
            price = None

        if user_data.direction == DirectionEnum.BUY and price is not None:
            if not balance or balance.available < user_data.qty * price:
                logger.warning(f'Недостаточный баланс RUB у пользователя {current_user.id}: доступно={balance.available if balance else 0}, требуется={user_data.qty * price}')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f'Insufficient balance for RUB'
                )
            balance.available -= user_data.qty * price
            logger.debug(f'Зарезервировано {user_data.qty * price} RUB для пользователя {current_user.id}')
        elif user_data.direction == DirectionEnum.SELL:
            if not balance or balance.available < user_data.qty:
                logger.warning(f'Недостаточный баланс {user_data.ticker} у пользователя {current_user.id}: доступно={balance.available if balance else 0}, требуется={user_data.qty}')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f'Insufficient balance for {user_data.ticker}'
                )
            balance.available -= user_data.qty
            logger.debug(f'Зарезервировано {user_data.qty} {user_data.ticker} для пользователя {current_user.id}')

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

        # Блокируем все подходящие ордера одним запросом
        logger.debug(f'Поиск совпадающих ордеров: direction={opposite_direction}, price_condition={price_condition}')
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
            .with_for_update(skip_locked=True)  # Используем skip_locked для предотвращения дедлоков
        )
        matching_orders = matching_orders.scalars().all()
        logger.debug(f'Найдено {len(matching_orders)} подходящих ордеров')

        if price is None:
            available_qty = sum(order.qty - order.filled for order in matching_orders)
            if available_qty < new_order.qty:
                logger.warning(f'Недостаточная ликвидность для рыночного ордера: доступно={available_qty}, требуется={new_order.qty}')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Insufficient liquidity for market order'
                )

            if user_data.direction == DirectionEnum.BUY:
                max_price = max(order.price for order in matching_orders)
                if not balance or balance.available < user_data.qty * max_price:
                    logger.warning(f'Недостаточный баланс для рыночного ордера: доступно={balance.available if balance else 0}, требуется={user_data.qty * max_price}')
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail='Insufficient balance for market order'
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
                logger.error(f'Совпадающий ордер {matching_order.id} не имеет цены')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail='Matching order has no price'
                )

            logger.debug(f'Создание транзакции: qty={match_qty}, price={transaction_price}')
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
                logger.debug(f'Ордер {matching_order.id} полностью исполнен')
            else:
                matching_order.status = StatusEnum.PARTIALLY_EXECUTED
                logger.debug(f'Ордер {matching_order.id} частично исполнен: filled={matching_order.filled}/{matching_order.qty}')

            total_filled += match_qty

            buyer = current_user.id if new_order.direction == DirectionEnum.BUY else matching_order.user_id
            seller = matching_order.user_id if new_order.direction == DirectionEnum.BUY else current_user.id

            logger.debug(f'Блокировка балансов участников сделки: buyer={buyer}, seller={seller}')
            buyer_balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == buyer)
                .with_for_update()
            )
            seller_balance = await session.scalar(
                select(BalanceModel)
                .where(BalanceModel.user_id == seller)
                .with_for_update()
            )

            if new_order.direction == DirectionEnum.BUY:
                if not buyer_balance:
                    logger.debug(f'Создание нового баланса RUB для покупателя {buyer}')
                    buyer_balance = BalanceModel(user_id=buyer, ticker='RUB', amount=0, available=0)
                    session.add(buyer_balance)
                buyer_balance.amount -= match_qty * transaction_price
                buyer_balance.available -= match_qty * transaction_price
                logger.debug(f'Обновлен баланс RUB покупателя {buyer}: amount={buyer_balance.amount}, available={buyer_balance.available}')

                if not seller_balance:
                    logger.debug(f'Создание нового баланса {new_order.ticker} для продавца {seller}')
                    seller_balance = BalanceModel(user_id=seller, ticker=new_order.ticker, amount=0, available=0)
                    session.add(seller_balance)
                seller_balance.amount -= match_qty
                seller_balance.available -= match_qty
                logger.debug(f'Обновлен баланс {new_order.ticker} продавца {seller}: amount={seller_balance.amount}, available={seller_balance.available}')
            else:
                if not seller_balance:
                    logger.debug(f'Создание нового баланса {new_order.ticker} для продавца {seller}')
                    seller_balance = BalanceModel(user_id=seller, ticker=new_order.ticker, amount=0, available=0)
                    session.add(seller_balance)
                seller_balance.amount -= match_qty
                seller_balance.available -= match_qty
                logger.debug(f'Обновлен баланс {new_order.ticker} продавца {seller}: amount={seller_balance.amount}, available={seller_balance.available}')

                if not buyer_balance:
                    logger.debug(f'Создание нового баланса RUB для покупателя {buyer}')
                    buyer_balance = BalanceModel(user_id=buyer, ticker='RUB', amount=0, available=0)
                    session.add(buyer_balance)
                buyer_balance.amount -= match_qty * transaction_price
                buyer_balance.available -= match_qty * transaction_price
                logger.debug(f'Обновлен баланс RUB покупателя {buyer}: amount={buyer_balance.amount}, available={buyer_balance.available}')

        new_order.filled = total_filled
        if total_filled == new_order.qty:
            new_order.status = StatusEnum.EXECUTED
            logger.debug(f'Новый ордер полностью исполнен: filled={total_filled}/{new_order.qty}')
        elif total_filled > 0 and price is not None:
            new_order.status = StatusEnum.PARTIALLY_EXECUTED
            logger.debug(f'Новый ордер частично исполнен: filled={total_filled}/{new_order.qty}')
        else:
            new_order.status = StatusEnum.NEW
            logger.debug(f'Новый ордер создан: filled={total_filled}/{new_order.qty}')

        if price is not None or new_order.status == StatusEnum.EXECUTED:
            session.add(new_order)

        logger.info(f'Ордер успешно создан: id={new_order.id}, filled={new_order.filled}, status={new_order.status}')
        return CreateOrderResponseSchema(
            success=True,
            order_id=new_order.id,
            filled_qty=new_order.filled,
            status=new_order.status
        )
    except Exception as e:
        logger.error(f'Ошибка при создании ордера: {str(e)}', exc_info=True)
        raise

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cannot cancel market order'
        )
    
    if order.direction == DirectionEnum.BUY:
        await update_balance(session, current_user.id, 'RUB', 0, (order.qty - order.filled) * order.price)
    else:
        await update_balance(session, current_user.id, order.ticker, 0, order.qty - order.filled)
    
    order.status = StatusEnum.CANCELLED 
    await session.commit()
    logger.info(f'Ордер id={order_id} отменен')
    return {'success': True}

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

@order_router.get('/api/v1/public/orderbook/{ticker}', response_model=OrderBookListSchema, tags=['public'])
async def get_order_book(
    session: SessionDep,
    ticker: str
):
    logger.info(f'Запрос стакана по тикеру {ticker}')
    bid_orders = await session.execute(
        select(OrderModel.price, func.sum(OrderModel.qty - OrderModel.filled))
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.BUY)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.price != None)
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.desc())
    )

    ask_orders = await session.execute(
        select(OrderModel.price, func.sum(OrderModel.qty - OrderModel.filled))
        .where(OrderModel.status.in_([StatusEnum.NEW, StatusEnum.PARTIALLY_EXECUTED]))
        .where(OrderModel.direction == DirectionEnum.SELL)
        .where(OrderModel.ticker == ticker)
        .where(OrderModel.price != None)
        .group_by(OrderModel.price)
        .order_by(OrderModel.price.asc())
    )

    bid_levels = [{'price': price, 'qty': qty} for price, qty in bid_orders]
    ask_levels = [{'price': price, 'qty': qty} for price, qty in ask_orders]

    logger.info(f'Получено {len(bid_levels)} бидов и {len(ask_levels)} асков для стакана {ticker}')
    return OrderBookListSchema(
        bid_levels=bid_levels,
        ask_levels=ask_levels
    )