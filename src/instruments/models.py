from uuid import uuid4
from typing import Optional

from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from src.database import Base


class InstrumentModel(Base):
    __tablename__ = 'instruments'

    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        default=lambda: str(uuid4()),
        nullable=False
    )

    name: Mapped[str] = mapped_column(
        nullable=False
    )

    ticker: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        unique=True
    )

    user_id: Mapped[Optional[str]] = mapped_column(  # <-- здесь важно
        UUID,
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )