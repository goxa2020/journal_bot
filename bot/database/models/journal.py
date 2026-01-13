from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.models.base import Base, created_at, updated_at, user_journal_association

if TYPE_CHECKING:
    from .grade import Grade
    from .user import User


class Journal(Base):
    __tablename__ = "journals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, unique=True)  # ID журнала в edu-tpi
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    teacher_name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[created_at] = mapped_column()
    updated_at: Mapped[updated_at] = mapped_column()

    # Relationships
    users: Mapped[list[User]] = relationship(secondary=user_journal_association, back_populates="journals")
    grades: Mapped[list[Grade]] = relationship("Grade", back_populates="journal", cascade="all, delete-orphan")
