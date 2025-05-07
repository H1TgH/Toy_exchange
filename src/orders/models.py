from enum import Enum as PyEnum
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Enum, String, Integer, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID

from src.database import Base


class DirectionEnum(PyEnum):
    BUY = 'BUY'
    SELL = 'SELL'

class StatusEnum(PyEnum):
    NEW = 'NEW'
    EXECUTED = 'EXECUTED'
    PARTIALLY_EXECUTED = 'PARTIALLY_EXECUTED'
    CANCELLED = 'CANCELLED'

class OrderModel(Base):
    __tablename__ = 'orders'

    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        default=lambda: str(uuid4()),
        nullable=False
    )

    user_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey('users.id', ondelete='CASCADE'),
        index=True,
        nullable=False
    )

    ticker: Mapped[str] = mapped_column(
        String(10),
        ForeignKey('instruments.ticker', ondelete='CASCADE'),
        nullable=False
    )

    direction: Mapped[DirectionEnum] = mapped_column(
        Enum(DirectionEnum),
        nullable=False
    )

    qty: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    price: Mapped[int] = mapped_column(
        Integer,
        nullable=True
    )

    filled: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    status: Mapped[StatusEnum] = mapped_column(
        Enum(StatusEnum),
        nullable=False,
        default=StatusEnum.NEW
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False
    )