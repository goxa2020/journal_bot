from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.models.base import Base, created_at

if TYPE_CHECKING:
    from datetime import datetime

    from .subject import Subject


class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    value: Mapped[str] = mapped_column(String(20), nullable=False)
    type_: Mapped[str] = mapped_column(String(50), nullable=False)  # exam/lab
    comment: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[created_at] = mapped_column()

    # Relationships
    subject: Mapped[Subject] = relationship(back_populates="grades")
