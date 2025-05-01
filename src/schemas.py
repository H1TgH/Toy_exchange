from typing import Literal
from pydantic import BaseModel, Field


class OkResponseSchema(BaseModel):
    success: Literal[True] = Field(default=True)
