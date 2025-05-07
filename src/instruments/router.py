from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.users.dependencies import get_current_admin
from src.instruments.models import InstrumentModel
from src.instruments.schemas import InstrumentCreateSchema


instrument_router = APIRouter()

@instrument_router.get('/api/v1/public/instrument', response_model=list[InstrumentCreateSchema], tags=['public'])
async def get_instruments_list(
    session: SessionDep
):
    result = await session.execute(select(InstrumentModel))

    instruments = result.scalars().all()

    return instruments

@instrument_router.post('/api/v1/admin/instrument', response_model=OkResponseSchema, tags=['admin'])
async def create_instrument(
    user_data: InstrumentCreateSchema,
    session: SessionDep,
    admin_user = Depends(get_current_admin)
):
    new_instrument = InstrumentModel(
        name = user_data.name,
        ticker = user_data.ticker,
        user_id = admin_user.id
    )
    
    session.add(new_instrument)
    await session.commit()

    return {'success': True}

@instrument_router.delete('/api/v1/admin/instrument/{ticker}', response_model=OkResponseSchema, tags=['admin'])
async def delete_instrument(
    session: SessionDep,
    ticker: str,
    admin_user = Depends(get_current_admin)
):
    instrument = await session.scalar(select(InstrumentModel).where(InstrumentModel.ticker == ticker))

    if not instrument:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Instrument not found"
        )

    await session.delete(instrument)
    await session.commit()

    return {"success": True}