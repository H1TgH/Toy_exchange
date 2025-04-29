from pydantic import BaseModel, field_validator

from src.auth.models import RoleEnum


class UserRegistrationSchema(BaseModel):
    name: str

    @field_validator('name')
    def validate_name(cls, name):
        if len(name) < 3:
            raise ValueError('Name too short')

class UserRegistrationResponceSchema(BaseModel):
    id: str
    name: str
    role: RoleEnum
    api_key: str
