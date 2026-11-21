"""Диф оценок и `sync_logs` (задача 2.5).

БД заменена словарём-хранилищем: проверяется логика дифа (новые/изменённые/пробелы),
а SQL-часть проверяется отдельно на реальном PostgreSQL.
"""

from __future__ import annotations
import datetime as dt
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.errors import EduAuthError, EduEmptyJournalError, EduUnavailableError, ParseError
from bot.database.models import Grade
from bot.database.models.sync_log import SyncStatus, SyncType
from bot.integrations.models import JournalBrief, JournalPayload, Lesson, StudentGrades
from bot.services.grade_sync import GradeSyncService, academic_year, current_semester
from bot.services.grades import GradesService
from bot.services.users import UserSyncInfo

USER = UserSyncInfo(
    id=1,
    is_authenticated=True,
    edu_user_id=1001,
    group_id=3273,
    group_name="584 ис-3",
    full_name="Студентов С.С.",
    language_code="ru",
)


def _lesson(hour: int, value: str, *, number: int | None = None) -> Lesson:
    return Lesson(
        date=dt.date(2024, 9, 30),
        hour_number=hour,
        edu_lesson_id=346734 + hour,
        value=value,
        number_value=number,
        is_mark=number is not None,
        is_pass=number is None and bool(value),
    )


def _payload(journal_id: int, lessons: tuple[Lesson, ...]) -> JournalPayload:
    return JournalPayload(
        journal_id=journal_id,
        name=f"Журнал {journal_id}",
        is_subgroup=False,
        students=(StudentGrades(student_id=1001, lessons=lessons),),
    )


class FakeTokens:
    async def call(self, operation: Any) -> Any:
        return await operation("token")


class FakeClient:
    def __init__(self, briefs: list[JournalBrief]) -> None:
        self.briefs = briefs
        self.sems: list[int] = []

    async def list_journals(self, _token: str, *, year: str, sem: int) -> list[JournalBrief]:
        self.sems.append(sem)
        return self.briefs if sem == 1 else []


class FakeCache:
    def __init__(
        self,
        payloads: dict[int, JournalPayload],
        errors: dict[int, Exception] | None = None,
    ) -> None:
        self.payloads = payloads
        self.errors = errors or {}

    async def get_journal(self, *, journal_id: int, **_kwargs: Any) -> JournalPayload:
        if journal_id in self.errors:
            raise self.errors[journal_id]
        return self.payloads[journal_id]


def _store_grade(journal_id: int, lesson: Lesson, age: dt.timedelta | None = None) -> Grade:
    return Grade(
        id=1,
        user_id=1,
        journal_id=journal_id,
        date=lesson.date,
        hour_number=lesson.hour_number,
        edu_lesson_id=lesson.edu_lesson_id,
        value=lesson.value,
        number_value=lesson.number_value,
        is_mark=lesson.is_mark,
        is_pass=lesson.is_pass,
        is_valid_pass=lesson.is_valid_pass,
        updated_at=dt.datetime.now(dt.UTC).replace(tzinfo=None) - (age or dt.timedelta(days=1)),
    )


@pytest.fixture
def sync_env(monkeypatch: pytest.MonkeyPatch):
    """Собрать сервис с подменёнными БД, кешем и токеном."""
    session = MagicMock()
    session.commit = AsyncMock()
    store: dict[tuple[int, int], Grade] = {}

    async def load_map(_session: Any, _user_id: int, journal_id: int) -> dict[tuple[dt.date, int], Grade]:
        return {
            (grade.date, grade.hour_number): grade
            for (stored_journal, _hour), grade in store.items()
            if stored_journal == journal_id
        }

    async def insert_lessons(_session: Any, _user_id: int, journal_id: int, lessons: list[Lesson]) -> int:
        for lesson in lessons:
            store[(journal_id, lesson.hour_number)] = _store_grade(journal_id, lesson)
        return len(lessons)

    log = AsyncMock()
    link = AsyncMock()
    user = AsyncMock(return_value=USER)
    monkeypatch.setattr(GradesService, "load_lesson_map", AsyncMock(side_effect=load_map))
    monkeypatch.setattr(GradesService, "insert_lessons", AsyncMock(side_effect=insert_lessons))
    monkeypatch.setattr("bot.services.grade_sync.load_user_sync_info", user)
    monkeypatch.setattr("bot.services.grade_sync.upsert_and_link", link)
    monkeypatch.setattr("bot.services.grade_sync.write_sync_log", log)

    return {
        "session": session,
        "store": store,
        "log": log,
        "link": link,
        "user": user,
    }


def _service(
    cache: FakeCache,
    briefs: list[JournalBrief],
    client: FakeClient | None = None,
) -> GradeSyncService:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return GradeSyncService(
        session=session,
        client=client or FakeClient(briefs),  # type: ignore[arg-type]
        cache=cache,  # type: ignore[arg-type]
        tokens=FakeTokens(),  # type: ignore[arg-type]
        sync_type=SyncType.MANUAL,
    )


async def test_first_sync_inserts_grades_and_writes_log(sync_env) -> None:
    lessons = (_lesson(1, "4", number=4), _lesson(2, "Н"))
    journal = JournalBrief(id=10, name="Журнал 10")
    service = _service(FakeCache({10: _payload(10, lessons)}), [journal])

    summary = await service.sync_user(1)

    assert summary.status == SyncStatus.SUCCESS
    assert summary.new_grades == 2
    assert summary.updated_grades == 0
    assert len(sync_env["store"]) == 2
    sync_env["link"].assert_awaited_once()
    log_args = sync_env["log"].await_args.kwargs
    assert log_args["new_grades_count"] == 2
    assert log_args["status"] == SyncStatus.SUCCESS


async def test_repeated_sync_is_idempotent(sync_env) -> None:
    lessons = (_lesson(1, "4", number=4), _lesson(2, "Н"))
    journal = JournalBrief(id=10, name="Журнал 10")
    service = _service(FakeCache({10: _payload(10, lessons)}), [journal])

    await service.sync_user(1)
    summary = await service.sync_user(1)

    assert summary.new_grades == 0
    assert summary.updated_grades == 0
    assert len(sync_env["store"]) == 2


async def test_changed_value_updates_grade_and_timestamp(sync_env) -> None:
    old = _lesson(1, "4", number=4)
    journal = JournalBrief(id=10, name="Журнал 10")
    sync_env["store"][(10, 1)] = _store_grade(10, old, age=dt.timedelta(days=3))
    before = sync_env["store"][(10, 1)].updated_at

    service = _service(FakeCache({10: _payload(10, (_lesson(1, "5", number=5),))}), [journal])
    summary = await service.sync_user(1)

    assert summary.updated_grades == 1
    assert summary.new_grades == 0
    grade = sync_env["store"][(10, 1)]
    assert grade.value == "5"
    assert grade.updated_at > before


async def test_trailing_spaces_do_not_count_as_change(sync_env) -> None:
    original = _lesson(1, "4", number=4)
    journal = JournalBrief(id=10, name="Журнал 10")
    sync_env["store"][(10, 1)] = _store_grade(10, original)
    service = _service(FakeCache({10: _payload(10, (_lesson(1, "4  ", number=4),))}), [journal])

    summary = await service.sync_user(1)

    assert summary.new_grades == 0
    assert summary.updated_grades == 0
    assert sync_env["store"][(10, 1)].value == "4"


async def test_empty_journal_is_skipped_without_error(sync_env) -> None:
    briefs = [JournalBrief(id=10, name="Журнал 10"), JournalBrief(id=11, name="Архивный")]
    cache = FakeCache({10: _payload(10, (_lesson(1, "4", number=4),))}, errors={11: EduEmptyJournalError("empty")})
    service = _service(cache, briefs)

    summary = await service.sync_user(1)

    assert summary.status == SyncStatus.SUCCESS
    assert summary.error_codes == []
    assert summary.new_grades == 1
    assert any(result.skipped for result in summary.journals)


async def test_one_broken_journal_does_not_fail_the_rest(sync_env) -> None:
    lessons = (_lesson(1, "4", number=4),)
    briefs = [JournalBrief(id=10, name="Журнал 10"), JournalBrief(id=11, name="Журнал 11")]
    cache = FakeCache({10: _payload(10, lessons)}, errors={11: ParseError("bad schema")})
    service = _service(cache, briefs)

    summary = await service.sync_user(1)

    assert summary.status == SyncStatus.FAILED
    assert summary.error_codes == ["parse"]
    assert summary.new_grades == 1
    assert len(summary.journals) == 2


async def test_all_unavailable_raises_for_retry(sync_env) -> None:
    briefs = [JournalBrief(id=10, name="Журнал 10")]
    cache = FakeCache({}, errors={10: EduUnavailableError("down")})
    service = _service(cache, briefs)

    with pytest.raises(EduUnavailableError):
        await service.sync_user(1)

    assert sync_env["log"].await_args.kwargs["status"] == SyncStatus.FAILED


async def test_auth_error_aborts_sync(sync_env) -> None:
    briefs = [JournalBrief(id=10, name="Журнал 10")]
    cache = FakeCache({}, errors={10: EduAuthError("bad")})
    service = _service(cache, briefs)

    with pytest.raises(EduAuthError):
        await service.sync_user(1)


async def test_unauthenticated_user_is_rejected(sync_env) -> None:
    sync_env["user"].return_value = UserSyncInfo(
        id=1,
        is_authenticated=False,
        edu_user_id=None,
        group_id=None,
        group_name=None,
        full_name=None,
        language_code="ru",
    )
    service = _service(FakeCache({}), [])

    with pytest.raises(EduAuthError):
        await service.sync_user(1)


def test_academic_year_switches_in_september() -> None:
    assert academic_year(dt.date(2026, 8, 31)) == "2025-2026"
    assert academic_year(dt.date(2026, 9, 1)) == "2026-2027"


def test_current_semester_does_not_request_the_future_one() -> None:
    assert current_semester(dt.date(2026, 9, 1)) == 1
    assert current_semester(dt.date(2026, 12, 31)) == 1
    assert current_semester(dt.date(2027, 1, 15)) == 1
    assert current_semester(dt.date(2027, 2, 1)) == 2
    assert current_semester(dt.date(2027, 6, 30)) == 2


async def test_sync_requests_only_current_semester(sync_env) -> None:
    client = FakeClient([JournalBrief(id=10, name="Журнал 10")])
    service = _service(FakeCache({10: _payload(10, ())}), [], client=client)

    await service.sync_user(1)

    assert client.sems == [current_semester()]
