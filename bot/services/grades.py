from __future__ import annotations
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from bot.database.models import Grade, Journal

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


class GradesService:
    """Сервис для работы с оценками (Grades)."""

    @classmethod
    async def create(  # noqa: PLR0913
        cls,
        session: AsyncSession,
        grade_id: int,
        user_id: int,
        journal_id: int,
        date: datetime,
        value: str,
        number_value: int | None = None,
        is_mark: bool = False,
        is_pass: bool = False,
        is_valid_pass: bool = False,
    ) -> Grade:
        """Создать новую оценку."""
        grade = Grade(
            id=grade_id,
            user_id=user_id,
            journal_id=journal_id,
            date=date,
            value=value,
            number_value=number_value,
            is_mark=is_mark,
            is_pass=is_pass,
            is_valid_pass=is_valid_pass,
        )
        session.add(grade)
        await session.commit()
        await session.refresh(grade)
        return grade

    @classmethod
    async def get_by_journal(
        cls,
        session: AsyncSession,
        journal_id: int,
        from_date: datetime | None = None,
    ) -> list[Grade]:
        """Получить оценки по предмету, опционально с даты."""
        query = select(Grade).filter_by(journal_id=journal_id)
        if from_date:
            query = query.filter(Grade.date >= from_date)
        query = query.order_by(Grade.date.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def get_recent(
        cls,
        session: AsyncSession,
        user_id: int,
        limit: int = 10,
    ) -> list[Grade]:
        """Получить последние оценки пользователя."""
        query = select(Grade).filter(Grade.user_id == user_id).order_by(Grade.date.desc()).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def stats(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """
        Статистика: средний балл по предметам (value как float).
        """
        query = (
            select(
                Journal.id,
                Journal.name,
                func.avg(Grade.number_value.cast(Float)).label("avg_grade"),
                func.count(Grade.number_value).label("count"),
            )
            .join(Grade, Grade.journal_id == Journal.id)
            .filter(Grade.user_id == user_id)
            .group_by(Journal.id, Journal.name)
            .order_by(Journal.name)
        )
        result = await session.execute(query)
        return [dict(row) for row in result.mappings()]
