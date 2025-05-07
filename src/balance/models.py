from uuid import uuid4

from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from src.database import Base


class BalanceModel(Base):
    __tablename__ = 'balance'

    id: Mapped[str] = mapped_column(
        UUID,
        default=lambda: str(uuid4()),
        primary_key=True
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

    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )