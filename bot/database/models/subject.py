from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.models.base import Base, created_at

if TYPE_CHECKING:
    from .grade import Grade
    from .user import UserModel


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    teacher: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[created_at] = mapped_column()

    __table_args__ = (UniqueConstraint("user_id", "code", name="unique_user_subject_code"),)

    # Relationships
    user: Mapped[UserModel] = relationship(back_populates="subjects")
    grades: Mapped[list[Grade]] = relationship("Grade", back_populates="subject", cascade="all, delete-orphan")
