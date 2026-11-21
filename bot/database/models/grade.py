from __future__ import annotations
import datetime as dt  # noqa: TC003 — SQLAlchemy разрешает Mapped[dt.date] в рантайме
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, ForeignKey, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.models.base import Base, created_at, updated_at

if TYPE_CHECKING:
    from .journal import Journal
    from .user import User


class Grade(Base):
    __tablename__ = "grades"

    # Суррогатный PK: dateID занятия одинаков у всех студентов группы и PK быть не может
    # (docs/ARCHITECTURE.md §8, решение A4).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    #: Номер пары в этот день — вторая часть ключа урока.
    hour_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    #: `dateID` из журнала: информационное поле, в дифе не участвует.
    edu_lesson_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    value: Mapped[str] = mapped_column(String(2), nullable=False)
    number_value: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_mark: Mapped[bool]
    is_pass: Mapped[bool]
    is_valid_pass: Mapped[bool]
    created_at: Mapped[created_at] = mapped_column()
    updated_at: Mapped[updated_at] = mapped_column()

    __table_args__ = (
        Index("idx_user_journal_date", "user_id", "journal_id", "date"),
        UniqueConstraint("user_id", "journal_id", "date", "hour_number", name="uq_grades_user_journal_date_hour"),
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="grades")
    journal: Mapped[Journal] = relationship(back_populates="grades")
