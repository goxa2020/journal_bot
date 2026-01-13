from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Journal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class JournalsService:
    """Сервис для работы с журналами (journals)."""

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        journal_id: int,
        name: str,
        teacher_name: str,
        lesson_type: str,
    ) -> Journal:
        """Создать новый предмет."""
        journal = Journal(id=journal_id, name=name, teacher_name=teacher_name, type=lesson_type)
        session.add(journal)
        await session.commit()
        await session.refresh(journal)
        return journal

    @classmethod
    async def get_by_user(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> list[Journal]:
        """Получить все предметы пользователя."""
        query = select(Journal).filter_by(user_id=user_id)
        result = await session.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def get_by_code(
        cls,
        session: AsyncSession,
        user_id: int,
        code: str,
    ) -> Journal | None:
        """Получить предмет по коду для пользователя."""
        query = select(Journal).filter_by(user_id=user_id, code=code)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def update(
        cls,
        session: AsyncSession,
        journal_id: int,
        name: str | None = None,
        code: str | None = None,
        teacher: str | None = None,
    ) -> None:
        """Обновить предмет."""
        updates = {
            k: v
            for k, v in {"name": name, "code": code, "teacher": teacher}.items()
            if v is not None  # Выборка
        }
        if not updates:
            return
        stmt = update(Journal).where(Journal.id == journal_id).values(**updates)
        await session.execute(stmt)
        await session.commit()

    @classmethod
    async def delete(
        cls,
        session: AsyncSession,
        journal_id: int,
    ) -> None:
        """Удалить предмет."""
        stmt = delete(Journal).where(Journal.id == journal_id)
        await session.execute(stmt)
        await session.commit()
