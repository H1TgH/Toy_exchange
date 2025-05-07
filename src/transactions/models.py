from sqlalchemy import String, Integer, ForeignKey, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from uuid import uuid4
from datetime import datetime, timezone

from src.database import Base


class TransactionModel(Base):
    __tablename__ = 'transactions'

    id: Mapped[str] = mapped_column(
        UUID,
        default=lambda: str(uuid4()),
        primary_key=True
    )

    buyer_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=True
    )

    seller_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=True
    )

    ticker: Mapped[str] = mapped_column(
        String(10),
        ForeignKey('instruments.ticker', ondelete='CASCADE'),
        nullable=False
    )

    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    price: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )