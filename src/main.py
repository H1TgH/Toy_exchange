from fastapi import FastAPI

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

app.include_router(auth_router)
app.include_router(instrument_router)
app.include_router(order_router)
app.include_router(balance_router)
app.include_router(transaction_router)