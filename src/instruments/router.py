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
    try:
        logger.info(f'[GET /api/v1/public/instrument] Начало запроса списка инструментов')
        result = await session.execute(select(InstrumentModel))
        instruments = result.scalars().all()
        logger.info(f'[GET /api/v1/public/instrument] Получено инструментов: {len(instruments)}')
        for instrument in instruments:
            logger.info(f'[GET /api/v1/public/instrument] Инструмент: ticker={instrument.ticker}, name={instrument.name}, created_by={instrument.user_id}')
        return instruments
    except Exception as e:
        logger.error(f'[GET /api/v1/public/instrument] Ошибка при получении списка инструментов: {str(e)}', exc_info=True)
        raise

@instrument_router.post('/api/v1/admin/instrument', response_model=OkResponseSchema, tags=['admin'])
async def create_instrument(
    user_data: InstrumentCreateSchema,
    session: SessionDep,
    admin_user = Depends(get_current_admin)
):
    try:
        logger.info(f'[POST /api/v1/admin/instrument] Админ {admin_user.id} инициировал создание инструмента: ticker={user_data.ticker}, name={user_data.name}')
        
        instrument = await session.scalar(
            select(InstrumentModel)
            .where(InstrumentModel.ticker == user_data.ticker)
        )

        if instrument:
            logger.warning(f'[POST /api/v1/admin/instrument] Попытка создания дубликата инструмента: ticker={user_data.ticker}, existing_name={instrument.name}, existing_creator={instrument.user_id}')
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
        logger.info(f'[POST /api/v1/admin/instrument] Успешно создан новый инструмент: ticker={new_instrument.ticker}, name={new_instrument.name}, created_by={admin_user.id}')
        return {'success': True}
    except Exception as e:
        logger.error(f'[POST /api/v1/admin/instrument] Ошибка при создании инструмента: {str(e)}', exc_info=True)
        raise

@instrument_router.delete('/api/v1/admin/instrument/{ticker}', response_model=OkResponseSchema, tags=['admin'])
async def delete_instrument(
    session: SessionDep,
    ticker: str,
    admin_user = Depends(get_current_admin)
):
    try:
        logger.info(f'[DELETE /api/v1/admin/instrument/{ticker}] Админ {admin_user.id} инициировал удаление инструмента: ticker={ticker}')
        
        instrument = await session.scalar(
            select(InstrumentModel)
            .where(InstrumentModel.ticker == ticker)
        )

        if not instrument:
            logger.warning(f'[DELETE /api/v1/admin/instrument/{ticker}] Попытка удаления несуществующего инструмента: ticker={ticker}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail='Instrument not found'
            )

        logger.info(f'[DELETE /api/v1/admin/instrument/{ticker}] Найден инструмент для удаления: ticker={instrument.ticker}, name={instrument.name}, created_by={instrument.user_id}')
        await session.delete(instrument)
        await session.commit()
        logger.info(f'[DELETE /api/v1/admin/instrument/{ticker}] Успешно удален инструмент: ticker={ticker}, admin_id={admin_user.id}')
        return {'success': True}
    except Exception as e:
        logger.error(f'[DELETE /api/v1/admin/instrument/{ticker}] Ошибка при удалении инструмента: {str(e)}', exc_info=True)
        raise