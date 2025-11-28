from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Subject

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SubjectsService:
    """Сервис для работы с предметами (Subjects)."""

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        user_id: int,
        name: str,
        code: str,
        teacher: str,
    ) -> Subject:
        """Создать новый предмет."""
        subject = Subject(
            user_id=user_id,
            name=name,
            code=code,
            teacher=teacher,
        )
        session.add(subject)
        await session.commit()
        await session.refresh(subject)
        return subject

    @classmethod
    async def get_by_user(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> list[Subject]:
        """Получить все предметы пользователя."""
        query = select(Subject).filter_by(user_id=user_id)
        result = await session.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def get_by_code(
        cls,
        session: AsyncSession,
        user_id: int,
        code: str,
    ) -> Subject | None:
        """Получить предмет по коду для пользователя."""
        query = select(Subject).filter_by(user_id=user_id, code=code)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def update(
        cls,
        session: AsyncSession,
        subject_id: int,
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
        stmt = update(Subject).where(Subject.id == subject_id).values(**updates)
        await session.execute(stmt)
        await session.commit()

    @classmethod
    async def delete(
        cls,
        session: AsyncSession,
        subject_id: int,
    ) -> None:
        """Удалить предмет."""
        stmt = delete(Subject).where(Subject.id == subject_id)
        await session.execute(stmt)
        await session.commit()
