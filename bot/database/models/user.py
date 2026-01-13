from __future__ import annotations
import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from .grade import Grade
    from .journal import Journal
    from .sync_log import SyncLog

from bot.database.models.base import Base, big_int_pk, created_at, updated_at, user_journal_association


class User(Base):
    __tablename__ = "users"

    id: Mapped[big_int_pk]
    language_code: Mapped[str | None]
    edu_login_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edu_password_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edu_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    group_name: Mapped[str | None]
    full_name: Mapped[str | None]
    is_authenticated: Mapped[bool] = mapped_column(default=False)
    notification_enabled: Mapped[bool] = mapped_column(default=True)
    morning_notification_enabled: Mapped[bool] = mapped_column(default=True)
    morning_notification_time: Mapped[datetime.time | None] = mapped_column(default=datetime.time(8, 0))
    watch_mode_expires_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    watch_mode_last_sync_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    journals: Mapped[list[Journal]] = relationship(secondary=user_journal_association, back_populates="users")
    grades: Mapped[list[Grade]] = relationship("Grade", back_populates="user")
    sync_logs: Mapped[list[SyncLog]] = relationship("SyncLog", back_populates="user")

    is_admin: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        Index("idx_telegram_id", "id"),
        Index("idx_group_id", "group_id"),
        Index("idx_group_edu_user", "id", "group_id"),
    )

    def __str__(self) -> str:
        return f"{self.id}: {self.full_name}"
