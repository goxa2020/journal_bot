from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, and_, func, select

from bot.core.config import TIMEZONE
from bot.database.models import Grade, Journal
from bot.database.models.base import user_journal_association

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.integrations.models import Lesson


@dataclass(frozen=True, slots=True)
class JournalSummary:
    """Журнал пользователя для экрана `/grades` — только данные из БД."""

    id: int
    name: str
    teacher_name: str
    type: str
    grades_count: int
    average: float | None


class GradesService:
    """Сервис для работы с оценками (Grades)."""

    @classmethod
    async def create(  # noqa: PLR0913, PLR0917
        cls,
        session: AsyncSession,
        user_id: int,
        journal_id: int,
        date: dt.datetime,
        value: str,
        number_value: int | None = None,
        is_mark: bool = False,
        is_pass: bool = False,
        is_valid_pass: bool = False,
        hour_number: int = 0,
        edu_lesson_id: int | None = None,
    ) -> Grade:
        """Создать новую оценку. PK — суррогатный, из edu-tpi больше не приходит."""
        grade = Grade(
            user_id=user_id,
            journal_id=journal_id,
            date=date,
            value=value,
            number_value=number_value,
            is_mark=is_mark,
            is_pass=is_pass,
            is_valid_pass=is_valid_pass,
            hour_number=hour_number,
            edu_lesson_id=edu_lesson_id,
        )
        session.add(grade)
        await session.commit()
        await session.refresh(grade)
        return grade

    @classmethod
    async def load_lesson_map(
        cls,
        session: AsyncSession,
        user_id: int,
        journal_id: int,
    ) -> dict[tuple[date, int], Grade]:
        """Существующие оценки журнала: ключ дифа — `(date, hour_number)`."""
        query = select(Grade).where(Grade.user_id == user_id, Grade.journal_id == journal_id)
        result = await session.execute(query)
        return {(grade.date, grade.hour_number): grade for grade in result.scalars().all()}

    @classmethod
    async def insert_lessons(
        cls,
        session: AsyncSession,
        user_id: int,
        journal_id: int,
        lessons: list[Lesson],
    ) -> int:
        """Добавить занятия в сессию (commit — на вызывающей стороне)."""
        session.add_all(
            [
                Grade(
                    user_id=user_id,
                    journal_id=journal_id,
                    date=lesson.date,
                    hour_number=lesson.hour_number,
                    edu_lesson_id=lesson.edu_lesson_id,
                    value=lesson.value,
                    number_value=lesson.number_value,
                    is_mark=lesson.is_mark,
                    is_pass=lesson.is_pass,
                    is_valid_pass=lesson.is_valid_pass,
                )
                for lesson in lessons
            ],
        )
        await session.flush()
        return len(lessons)

    @classmethod
    async def update_lesson(cls, grade: Grade, lesson: Lesson) -> None:
        """Обновить изменившееся занятие; `updated_at` — явно (диф виден в БД)."""
        grade.edu_lesson_id = lesson.edu_lesson_id
        grade.value = lesson.value
        grade.number_value = lesson.number_value
        grade.is_mark = lesson.is_mark
        grade.is_pass = lesson.is_pass
        grade.is_valid_pass = lesson.is_valid_pass
        grade.updated_at = dt.datetime.now(TIMEZONE).replace(tzinfo=None)

    @classmethod
    async def get_by_journal(
        cls,
        session: AsyncSession,
        journal_id: int,
        from_date: dt.datetime | None = None,
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
    async def get_last_grade(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> tuple[str, str, date] | None:
        """Последняя оценка пользователя и название журнала (для главного меню).

        Join выполняется в том же запросе: в async-контексте ленивая загрузка
        `grade.journal` невозможна. Возвращает `None`, если оценок ещё нет.
        """
        query = (
            select(Grade.value, Journal.name, Grade.date)
            .join(Journal, Journal.id == Grade.journal_id)
            .where(Grade.user_id == user_id)
            .order_by(Grade.date.desc(), Grade.id.desc())
            .limit(1)
        )
        result = await session.execute(query)
        row = result.first()
        if row is None:
            return None
        value, journal_name, grade_date = row
        return value, journal_name, grade_date

    @classmethod
    async def list_journals(cls, session: AsyncSession, user_id: int) -> list[JournalSummary]:
        """Журналы пользователя со средним баллом и числом оценок.

        Источник — `student_journal`, поэтому журнал виден и до первой оценки
        (после входа синхронизация уже создала связи).
        """
        grade_join = and_(Grade.journal_id == Journal.id, Grade.user_id == user_id)
        query = (
            select(
                Journal.id,
                Journal.name,
                Journal.teacher_name,
                Journal.type,
                func.count(Grade.id).label("grades_count"),
                func.avg(Grade.number_value.cast(Float)).label("average"),
            )
            .select_from(Journal)
            .join(user_journal_association, user_journal_association.c.journal_id == Journal.id)
            .outerjoin(Grade, grade_join)
            .where(user_journal_association.c.user_id == user_id)
            .group_by(Journal.id, Journal.name, Journal.teacher_name, Journal.type)
            .order_by(Journal.name)
        )
        result = await session.execute(query)
        return [
            JournalSummary(
                id=row.id,
                name=row.name,
                teacher_name=row.teacher_name,
                type=row.type,
                grades_count=int(row.grades_count or 0),
                average=float(row.average) if row.average is not None else None,
            )
            for row in result.all()
        ]

    @classmethod
    async def get_journal_summary(
        cls,
        session: AsyncSession,
        user_id: int,
        journal_id: int,
    ) -> JournalSummary | None:
        """Один журнал пользователя со средним баллом; `None` — журнала нет."""
        grade_join = and_(Grade.journal_id == Journal.id, Grade.user_id == user_id)
        query = (
            select(
                Journal.id,
                Journal.name,
                Journal.teacher_name,
                Journal.type,
                func.count(Grade.id).label("grades_count"),
                func.avg(Grade.number_value.cast(Float)).label("average"),
            )
            .select_from(Journal)
            .join(user_journal_association, user_journal_association.c.journal_id == Journal.id)
            .outerjoin(Grade, grade_join)
            .where(
                user_journal_association.c.user_id == user_id,
                Journal.id == journal_id,
            )
            .group_by(Journal.id, Journal.name, Journal.teacher_name, Journal.type)
        )
        row = (await session.execute(query)).first()
        if row is None:
            return None
        return JournalSummary(
            id=row.id,
            name=row.name,
            teacher_name=row.teacher_name,
            type=row.type,
            grades_count=int(row.grades_count or 0),
            average=float(row.average) if row.average is not None else None,
        )

    @classmethod
    async def journal_belongs_to_user(cls, session: AsyncSession, user_id: int, journal_id: int) -> bool:
        """Есть ли у пользователя этот журнал (защита от чужих id в callback)."""
        query = (
            select(user_journal_association.c.journal_id)
            .where(
                user_journal_association.c.user_id == user_id,
                user_journal_association.c.journal_id == journal_id,
            )
            .limit(1)
        )
        return (await session.execute(query)).first() is not None

    @classmethod
    async def get_journal_grades(cls, session: AsyncSession, user_id: int, journal_id: int) -> list[Grade]:
        """Оценки пользователя по журналу в порядке дат и пар."""
        query = (
            select(Grade)
            .where(Grade.user_id == user_id, Grade.journal_id == journal_id)
            .order_by(Grade.date, Grade.hour_number)
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
