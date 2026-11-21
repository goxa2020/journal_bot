"""Запись истории синхронизаций (`sync_logs`, docs/ARCHITECTURE.md §4.1)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from bot.database.models.sync_log import SyncLog, SyncStatus, SyncType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: `sync_logs.message` — VARCHAR(500); длинные списки ошибок обрезаем.
MESSAGE_MAX_LENGTH = 500


async def write_sync_log(  # noqa: PLR0913
    session: AsyncSession,
    *,
    user_id: int,
    sync_type: SyncType,
    status: SyncStatus,
    new_grades_count: int = 0,
    updated_grades_count: int = 0,
    message: str | None = None,
) -> SyncLog:
    """Сохранить результат синхронизации; в сообщении нет логинов и оценок."""
    log = SyncLog(
        user_id=user_id,
        sync_type=sync_type,
        status=status,
        new_grades_count=new_grades_count,
        updated_grades_count=updated_grades_count,
        message=message[:MESSAGE_MAX_LENGTH] if message else None,
    )
    session.add(log)
    await session.commit()
    return log
