from enum import Enum as PyEnum
from datetime import datetime

from sqlalchemy import BigInteger, String, Enum,  func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class RoleEnum(PyEnum):
    USER = 'USER'
    ADMIN = 'ADMIN'

class UserModel(Base):
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        unique= True,
        nullable=False
    )

    name: Mapped[str] = mapped_column(
        String(64),
        nullable=False
    )

    role: Mapped[RoleEnum] = mapped_column(
        Enum(RoleEnum),
        nullable=False,
        default=RoleEnum.USER
    )

    api_key: Mapped[str] = mapped_column(
        nullable=False,
        unique=True
    )

    created_at = Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now()
    )