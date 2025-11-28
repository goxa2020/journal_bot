from __future__ import annotations
import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from .journal_parser import InvalidCredsError, JournalParser, ParseError
from bot.services.grades import GradesService
from bot.services.subjects import SubjectsService
from bot.services.sync_logs import SyncLogsService
from bot.services.users import get_edu_credentials

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.database.models.grade import Grade
    from bot.database.models.subject import Subject


async def sync_grades_for_user(
    session: AsyncSession,
    user_id: int,
) -> int:
    """
    Синхронизирует оценки пользователя:
    - Получает credentials
    - Парсит оценки
    - Для каждого предмета: находит/создает Subject, upsert Grades (по date/value)
    - Логирует sync (success/error, count новых grades)
    Возвращает количество новых оценок.
    """
    # Получить credentials
    username, password = await get_edu_credentials(session, user_id)
    if username is None or password is None:
        await SyncLogsService.create(
            session, user_id, status="error", error_msg="Нет учетных данных"
        )
        return 0

    parser = JournalParser()
    new_grades_count = 0

    try:
        parsed_data = await parser.parse_grades(username, password)
    except InvalidCredsError:
        await SyncLogsService.create(
            session, user_id, status="error", error_msg="Неверные учетные данные"
        )
        return 0
    except ParseError as e:
        await SyncLogsService.create(
            session, user_id, status="error", error_msg=f"Ошибка парсинга: {e!s}"
        )
        return 0
    except Exception as e:  # noqa: BLE001
        await SyncLogsService.create(
            session, user_id, status="error", error_msg=f"Неожиданная ошибка: {e!s}"
        )
        return 0

    # Обработка parsed data
    for subj_data in parsed_data:
        subject_info = subj_data["subject"]
        code = subject_info["code"]
        name = subject_info["name"]
        teacher = subject_info["teacher"]

        # Найти или создать Subject
        existing_subject: Subject | None = await SubjectsService.get_by_code(
            session, user_id, code
        )
        if not existing_subject:
            existing_subject = await SubjectsService.create(
                session, user_id, name, code, teacher
            )

        # Получить существующие grades
        existing_grades: list[Grade] = await GradesService.get_by_subject(
            session, existing_subject.id
        )
        existing_keys = {(g.date.isoformat(), g.value) for g in existing_grades}

        # Upsert new grades
        for grade_data in subj_data["grades"]:
            date_str = grade_data["date"]
            try:
                date = datetime.fromisoformat(date_str)
            except ValueError:
                continue  # Skip invalid date

            key = (date_str, grade_data["value"])
            if key not in existing_keys:
                await GradesService.create(
                    session,
                    existing_subject.id,
                    date,
                    grade_data["value"],
                    grade_data["type"],
                    grade_data.get("comment"),
                )
                new_grades_count += 1

        # Rate limit между предметами
        await asyncio.sleep(1.5)

    # Лог успеха
    await SyncLogsService.create(
        session, user_id, status="success", grades_count=new_grades_count
    )

    return new_grades_count
