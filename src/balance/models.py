from uuid import uuid4, UUID
from sqlalchemy import String, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from src.database import Base

class BalanceModel(Base):
    __tablename__ = 'balance'

    id: Mapped[UUID] = mapped_column(
        PGUUID,
        default=uuid4,
        primary_key=True
    )
    
    user_id: Mapped[UUID] = mapped_column(
        PGUUID,
        ForeignKey('users.id', ondelete='CASCADE'),
        index=True,
        nullable=False
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

    available: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    __table_args__ = (
        Index('idx_balance_user_ticker', 'user_id', 'ticker', unique=True),
        Index('idx_balance_ticker_amount', 'ticker', 'amount'),
    )