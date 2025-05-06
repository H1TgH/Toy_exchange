from fastapi import FastAPI

from src.users.router import auth_router
from src.instruments.router import instrument_router


app = FastAPI()
app.include_router(auth_router)
app.include_router(instrument_router)