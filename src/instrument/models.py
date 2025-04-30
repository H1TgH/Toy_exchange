from uuid import uuid4

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from src.database import Base


class InstrumentModel(Base):
    __tablename__ = 'instriments'

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