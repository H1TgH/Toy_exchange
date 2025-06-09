from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.users.dependencies import get_current_admin
from src.instruments.models import InstrumentModel
from src.instruments.schemas import InstrumentCreateSchema
from src.logger import logger


instrument_router = APIRouter()

@instrument_router.get('/api/v1/public/instrument', response_model=list[InstrumentCreateSchema], tags=['public'])
async def get_instruments_list(
    session: SessionDep
):
    logger.info('Запрос списка инструментов')
    result = await session.execute(select(InstrumentModel))
    instruments = result.scalars().all()
    logger.info(f'Получено инструментов: {len(instruments)}')
    return instruments

@instrument_router.post('/api/v1/admin/instrument', response_model=OkResponseSchema, tags=['admin'])
async def create_instrument(
    user_data: InstrumentCreateSchema,
    session: SessionDep,
    admin_user = Depends(get_current_admin)
):
    logger.info(f'Пользователь {admin_user.id} пытается создать инструмент с тикером {user_data.ticker}')
    instrument = await session.scalar(
        select(InstrumentModel)
        .where(InstrumentModel.ticker == user_data.ticker)
    )

    if instrument:
        logger.warning(f'Инструмент с тикером {user_data.ticker} уже существует')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Instrument already exists'
        )
    
    new_instrument = InstrumentModel(
        name = user_data.name,
        ticker = user_data.ticker,
        user_id = admin_user.id
    )
    
    session.add(new_instrument)
    await session.commit()
    logger.info(f'Инструмент {user_data.ticker} создан пользователем {admin_user.id}')
    return {'success': True}

@instrument_router.delete('/api/v1/admin/instrument/{ticker}', response_model=OkResponseSchema, tags=['admin'])
async def delete_instrument(
    session: SessionDep,
    ticker: str,
    admin_user = Depends(get_current_admin)
):
    logger.info(f'Пользователь {admin_user.id} пытается удалить инструмент с тикером {ticker}')
    instrument = await session.scalar(
        select(InstrumentModel)
        .where(InstrumentModel.ticker == ticker)
    )

    if not instrument:
        logger.warning(f'Инструмент с тикером {ticker} не найден')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail='Instrument not found'
        )

    await session.delete(instrument)
    await session.commit()
    logger.info(f'Инструмент {ticker} удален пользователем {admin_user.id}')
    return {'success': True}