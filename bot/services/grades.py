from __future__ import annotations
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from bot.database.models import Grade, Subject

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


class GradesService:
    """Сервис для работы с оценками (Grades)."""

    @classmethod
    async def create(  # noqa: PLR0913
        cls,
        session: AsyncSession,
        subject_id: int,
        date: datetime,
        value: str,
        type_: str,
        comment: str | None = None,
    ) -> Grade:
        """Создать новую оценку."""
        grade = Grade(
            subject_id=subject_id,
            date=date,
            value=value,
            type_=type_,
            comment=comment,
        )
        session.add(grade)
        await session.commit()
        await session.refresh(grade)
        return grade

    @classmethod
    async def get_by_subject(
        cls,
        session: AsyncSession,
        subject_id: int,
        from_date: datetime | None = None,
    ) -> list[Grade]:
        """Получить оценки по предмету, опционально с даты."""
        query = select(Grade).filter_by(subject_id=subject_id)
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
        query = (
            select(Grade)
            .join(Subject, Grade.subject_id == Subject.id)
            .filter(Subject.user_id == user_id)
            .order_by(Grade.date.desc())
            .limit(limit)
        )
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
                Subject.id,
                Subject.name,
                func.avg(Grade.value.cast(Float)).label("avg_grade"),
                func.count(Grade.id).label("count"),
            )
            .join(Grade, Grade.subject_id == Subject.id)
            .filter(Subject.user_id == user_id)
            .group_by(Subject.id, Subject.name)
            .order_by(Subject.name)
        )
        result = await session.execute(query)
        return [dict(row) for row in result.mappings()]
