"""Журналы: upsert по id edu-tpi и связь «студент ↔ журнал» (задача 2.11).

`journals.id` — это `journalID` из edu-tpi, поэтому повторная синхронизация не должна
создавать дубликаты: вставка идёт через `INSERT ... ON CONFLICT (id) DO UPDATE`.
Связь `student_journal` — `ON CONFLICT DO NOTHING`: чужие связи не трогаем, M2M не
теряет журналы, которые уже были у пользователя.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.database.models import Journal
from bot.database.models.base import user_journal_association

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.integrations.models import JournalBrief


async def upsert_journal(session: AsyncSession, brief: JournalBrief) -> None:
    """Вставить журнал или обновить его название, преподавателя и тип."""
    stmt = pg_insert(Journal).values(
        id=brief.id,
        name=brief.name,
        teacher_name=brief.teacher_name,
        type=brief.type,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Journal.id],
        set_={
            "name": stmt.excluded.name,
            "teacher_name": stmt.excluded.teacher_name,
            "type": stmt.excluded.type,
        },
    )
    await session.execute(stmt)


async def link_student_journal(session: AsyncSession, user_id: int, journal_id: int) -> None:
    """Добавить связь пользователя с журналом, не создавая дубликатов."""
    stmt = (
        pg_insert(user_journal_association)
        .values(user_id=user_id, journal_id=journal_id)
        .on_conflict_do_nothing(index_elements=["user_id", "journal_id"])
    )
    await session.execute(stmt)


async def upsert_and_link(session: AsyncSession, user_id: int, brief: JournalBrief) -> None:
    """Обе операции подряд: журнал в `journals`, связь в `student_journal`."""
    await upsert_journal(session, brief)
    await link_student_journal(session, user_id, brief.id)
