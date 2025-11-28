from __future__ import annotations
import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.models.base import Base

if TYPE_CHECKING:
    import datetime

    from .user import UserModel


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("TIMEZONE('utc+3', now())")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success/error
    error_msg: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    grades_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # Relationships
    user: Mapped[UserModel] = relationship(back_populates="sync_logs")
