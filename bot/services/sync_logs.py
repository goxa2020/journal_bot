from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import SyncLog
from bot.database.models.sync_logs import SyncStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SyncLogsService:
    """Сервис для работы с логами синхронизации (SyncLogs)."""

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        user_id: int,
        status: str,
        error_msg: str | None = None,
        grades_count: int = 0,
    ) -> SyncLog:
        """Создать лог синхронизации."""
        log = SyncLog(
            user_id=user_id,
            status=status,
            error_msg=error_msg,
            grades_count=grades_count,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log

    @classmethod
    async def get_recent(
        cls,
        session: AsyncSession,
        user_id: int,
        limit: int = 5,
    ) -> list[SyncLog]:
        """Получить последние логи пользователя."""
        query = (
            select(SyncLog)  # Запрос
            .filter_by(user_id=user_id)
            .order_by(desc(SyncLog.created_at))
            .limit(limit)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def get_errors(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> list[SyncLog]:
        """Получить логи с ошибками пользователя."""
        query = (
            select(SyncLog)  # Запрос
            .filter_by(user_id=user_id, status=SyncStatus.FAILED)
            .order_by(desc(SyncLog.created_at))
        )
        result = await session.execute(query)
        return list(result.scalars().all())
