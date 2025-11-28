from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from datetime import datetime

    from .subject import Subject
    from .sync_log import SyncLog

from bot.database.models.base import Base, big_int_pk, created_at


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[big_int_pk]
    first_name: Mapped[str]
    last_name: Mapped[str | None]
    username: Mapped[str | None]
    language_code: Mapped[str | None]
    referrer: Mapped[str | None]
    created_at: Mapped[created_at]

    is_admin: Mapped[bool] = mapped_column(default=False)
    is_suspicious: Mapped[bool] = mapped_column(default=False)
    is_block: Mapped[bool] = mapped_column(default=False)
    is_premium: Mapped[bool] = mapped_column(default=False)

    edu_username_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    edu_password_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    student_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notifications_enabled: Mapped[bool] = mapped_column(default=False)

    subjects: Mapped[list[Subject]] = relationship("Subject", back_populates="user")
    sync_logs: Mapped[list[SyncLog]] = relationship("SyncLog", back_populates="user")

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"
