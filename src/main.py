from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.logger import logger
from src.users.router import auth_router
from src.instruments.router import instrument_router
from src.orders.router import order_router
from src.balance.router import balance_router
from src.transactions.router import transaction_router


app = FastAPI(
    title='Trading API',
    openapi_tags=[
        {
            'name': 'public',
        },
        {
            'name': 'balance',
        },
        {
            'name': 'order',
        },
        {
            'name': 'admin',
        },
        {
            'name': 'user',
        }
    ]
)

@app.middleware("http")
async def log_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(f'[ERROR] {request.method} {request.url.path}: {str(e)}', exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )

app.include_router(auth_router)
app.include_router(instrument_router)
app.include_router(order_router)
app.include_router(balance_router)
app.include_router(transaction_router)