from fastapi import APIRouter, Depends

from src.database import SessionDep
from src.schemas import OkResponseSchema
from src.auth.dependencies import get_current_admin
from src.instrument.models import InstrumentModel
from src.instrument.schemas import InstrumentCreateSchema


instrument_router = APIRouter()

@instrument_router.post('/api/v1/admin/instrument', response_model=OkResponseSchema)
async def create_instrument(
    user_data: InstrumentCreateSchema,
    session: SessionDep,
    admin_user = Depends(get_current_admin)
):
    new_instrument = InstrumentModel(
        name=user_data.name,
        ticker=user_data.ticker,
        user_id=admin_user.id
    )
    session.add(new_instrument)
    await session.commit()

    return {'success': True}