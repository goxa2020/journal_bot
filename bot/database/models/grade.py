from __future__ import annotations
import datetime as datatime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, ForeignKey, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.models.base import Base, created_at, updated_at

if TYPE_CHECKING:
    import datetime as datatime

    from .journal import Journal
    from .user import User


class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id"), index=True)
    date: Mapped[datatime.date] = mapped_column(Date, nullable=False)
    value: Mapped[str] = mapped_column(String(2), nullable=False)
    number_value: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_mark: Mapped[bool]
    is_pass: Mapped[bool]
    is_valid_pass: Mapped[bool]
    created_at: Mapped[created_at] = mapped_column()
    updated_at: Mapped[updated_at] = mapped_column()

    __table_args__ = (
        Index("idx_user_lesson", "id", "user_id"),
        Index("idx_user_journal_date", "user_id", "journal_id", "date"),
        UniqueConstraint("id", "user_id", "journal_id", name="uq_user_lesson_journal"),
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="grades")
    journal: Mapped[Journal] = relationship(back_populates="grades")
