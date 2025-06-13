from sqlalchemy import String, Integer, ForeignKey, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from uuid import uuid4, UUID
from datetime import datetime, timezone

from src.database import Base


class TransactionModel(Base):
    __tablename__ = 'transactions'

    id: Mapped[UUID] = mapped_column(
        PGUUID,
        default=uuid4,
        primary_key=True
    )

    buyer_id: Mapped[UUID] = mapped_column(
        PGUUID,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=True
    )

    seller_id: Mapped[UUID] = mapped_column(
        PGUUID,
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

    __table_args__ = (
        Index('idx_transactions_ticker_timestamp', 'ticker', 'timestamp'),
        Index('idx_transactions_buyer_seller', 'buyer_id', 'seller_id'),
    )