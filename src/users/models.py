from enum import Enum as PyEnum
from datetime import datetime
from uuid import uuid4, UUID

from sqlalchemy import String, Enum,  func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from src.database import Base


class RoleEnum(PyEnum):
    USER = 'USER'
    ADMIN = 'ADMIN'

class UserModel(Base):
    __tablename__ = 'users'
    
    id: Mapped[UUID] = mapped_column(
        PGUUID,
        primary_key=True,
        default=uuid4,
        unique= True,
        nullable=False,
        index=True
    )

    name: Mapped[str] = mapped_column(
        nullable=False
    )

    role: Mapped[RoleEnum] = mapped_column(
        Enum(RoleEnum),
        nullable=False,
        default=RoleEnum.USER
    )

    api_key: Mapped[str] = mapped_column(
        String(43),
        nullable=False,
        index=True,
        unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now()
    )