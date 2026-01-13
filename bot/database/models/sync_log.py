from __future__ import annotations
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.models.base import Base, created_at

if TYPE_CHECKING:
    from .user import User


class SyncType(Enum):
    MANUAL = "manual"
    AUTO = "auto"
    WATCH_MODE = "watch_mode"


class SyncStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    CANCELLED = "cancelled"


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    sync_type: Mapped[SyncType] = mapped_column(nullable=False)
    status: Mapped[SyncStatus] = mapped_column(String(15), nullable=False)
    new_grades_count: Mapped[int] = mapped_column(nullable=True)
    updated_grades_count: Mapped[int] = mapped_column(nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[created_at] = mapped_column()

    # Relationships
    user: Mapped[User] = relationship(back_populates="sync_logs")
