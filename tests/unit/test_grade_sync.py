"""Диф оценок и `sync_logs` (задача 2.5).

БД заменена словарём-хранилищем: проверяется логика дифа (новые/изменённые/пробелы),
а SQL-часть проверяется отдельно на реальном PostgreSQL.
"""

from __future__ import annotations
import datetime as dt
import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.errors import EduAuthError, EduEmptyJournalError, EduUnavailableError, ParseError
from bot.database.models import Grade
from bot.database.models.sync_log import SyncStatus, SyncType
from bot.integrations.models import JournalBrief, JournalPayload, Lesson, StudentGrades
from bot.services.grade_sync import GradeSyncService, NewGradeNotice, SyncSummary, academic_year, current_semester
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

    async def match_student(
        self,
        payload: JournalPayload,
        *,
        edu_user_id: int,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> int | None:
        return payload.resolve_student_id(edu_user_id, fio=fio, full_name=full_name)

    async def resolve_student_id(
        self,
        payload: JournalPayload,
        *,
        edu_user_id: int,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> int:
        student_id = await self.match_student(payload, edu_user_id=edu_user_id, fio=fio, full_name=full_name)
        if student_id is None:
            msg = f"Студент {edu_user_id} не найден в журнале {payload.journal_id}"
            raise ParseError(msg)
        return student_id


def _store_grade(
    journal_id: int,
    lesson: Lesson,
    age: dt.timedelta | None = None,
    *,
    user_id: int = 1,
) -> Grade:
    return Grade(
        id=1,
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
        updated_at=dt.datetime.now(dt.UTC).replace(tzinfo=None) - (age or dt.timedelta(days=1)),
    )


@pytest.fixture
def sync_env(monkeypatch: pytest.MonkeyPatch):
    """Собрать сервис с подменёнными БД, кешем и токеном."""
    session = MagicMock()
    session.commit = AsyncMock()
    store: dict[tuple[int, int, int], Grade] = {}

    async def load_map(_session: Any, user_id: int, journal_id: int) -> dict[tuple[dt.date, int], Grade]:
        return {
            (grade.date, grade.hour_number): grade
            for (stored_user, stored_journal, _hour), grade in store.items()
            if stored_user == user_id and stored_journal == journal_id
        }

    async def insert_lessons(_session: Any, user_id: int, journal_id: int, lessons: list[Lesson]) -> int:
        for lesson in lessons:
            store[(user_id, journal_id, lesson.hour_number)] = _store_grade(
                journal_id,
                lesson,
                user_id=user_id,
            )
        return len(lessons)

    log = AsyncMock()
    link = AsyncMock()
    user = AsyncMock(return_value=USER)
    monkeypatch.setattr(GradesService, "load_lesson_map", AsyncMock(side_effect=load_map))
    monkeypatch.setattr(GradesService, "insert_lessons", AsyncMock(side_effect=insert_lessons))
    monkeypatch.setattr("bot.services.grade_sync.load_user_sync_info", user)
    monkeypatch.setattr("bot.services.grade_sync.load_group_members", AsyncMock(return_value=[]))
    monkeypatch.setattr("bot.services.grade_sync.upsert_and_link", link)
    monkeypatch.setattr("bot.services.grade_sync.write_sync_log", log)

    return {
        "session": session,
        "store": store,
        "log": log,
        "link": link,
        "user": user,
    }


def _service(  # noqa: PLR0913 — тестовый конструктор сервиса
    cache: FakeCache,
    briefs: list[JournalBrief],
    client: FakeClient | None = None,
    *,
    opportunistic: bool = False,
    notifier: Any = None,
    user_lock: Any = None,
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
        opportunistic=opportunistic,
        notifier=notifier,
        user_lock=user_lock,
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
    sync_env["store"][(1, 10, 1)] = _store_grade(10, old, age=dt.timedelta(days=3))
    before = sync_env["store"][(1, 10, 1)].updated_at

    service = _service(FakeCache({10: _payload(10, (_lesson(1, "5", number=5),))}), [journal])
    summary = await service.sync_user(1)

    assert summary.updated_grades == 1
    assert summary.new_grades == 0
    grade = sync_env["store"][(1, 10, 1)]
    assert grade.value == "5"
    assert grade.updated_at > before


async def test_trailing_spaces_do_not_count_as_change(sync_env) -> None:
    original = _lesson(1, "4", number=4)
    journal = JournalBrief(id=10, name="Журнал 10")
    sync_env["store"][(1, 10, 1)] = _store_grade(10, original)
    service = _service(FakeCache({10: _payload(10, (_lesson(1, "4  ", number=4),))}), [journal])

    summary = await service.sync_user(1)

    assert summary.new_grades == 0
    assert summary.updated_grades == 0
    assert sync_env["store"][(1, 10, 1)].value == "4"


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


async def test_new_notices_describe_exactly_the_new_lessons(sync_env) -> None:
    lessons = (_lesson(1, "4", number=4), _lesson(2, "Н"))
    journal = JournalBrief(id=10, name="Журнал 10", type="Лек")
    service = _service(FakeCache({10: _payload(10, lessons)}), [journal])

    summary = await service.sync_user(1)

    assert [notice.lesson_key for notice in summary.new_notices] == [
        "10:2024-09-30:1",
        "10:2024-09-30:2",
    ]
    first, second = summary.new_notices
    assert first.journal_id == 10
    assert first.journal_name == "Журнал 10"
    assert first.journal_type == "Лек"
    assert first.date == dt.date(2024, 9, 30)
    assert first.value == "4"
    assert first.number_value == 4
    assert first.is_mark is True
    assert second.value == "Н"
    assert second.is_pass is True


async def test_changed_grade_is_not_a_new_notice(sync_env) -> None:
    journal = JournalBrief(id=10, name="Журнал 10")
    sync_env["store"][(1, 10, 1)] = _store_grade(10, _lesson(1, "4", number=4))
    service = _service(FakeCache({10: _payload(10, (_lesson(1, "5", number=5),))}), [journal])

    summary = await service.sync_user(1)

    assert summary.updated_grades == 1
    assert summary.new_grades == 0
    assert summary.new_notices == []


async def test_repeated_sync_has_no_new_notices(sync_env) -> None:
    journal = JournalBrief(id=10, name="Журнал 10")
    lessons = (_lesson(1, "4", number=4),)
    service = _service(FakeCache({10: _payload(10, lessons)}), [journal])

    await service.sync_user(1)
    summary = await service.sync_user(1)

    assert summary.new_grades == 0
    assert summary.new_notices == []


def test_sync_summary_as_dict_stays_json_safe() -> None:
    notice = NewGradeNotice(
        journal_id=10,
        journal_name="Журнал 10",
        journal_type="Лек",
        date=dt.date(2024, 9, 30),
        hour_number=1,
        value="4",
        number_value=4,
        is_mark=True,
    )
    summary = SyncSummary(
        user_id=1,
        sync_type=SyncType.MANUAL,
        status=SyncStatus.SUCCESS,
        new_grades=1,
        new_notices=[notice],
        language_code="ru",
    )

    payload = summary.as_dict()

    assert json.loads(json.dumps(payload)) == payload
    assert payload["new_notices"] == 1
    assert "notices" not in payload


def test_new_grade_notice_dict_roundtrip() -> None:
    notice = NewGradeNotice(
        journal_id=10,
        journal_name="Журнал 10",
        journal_type="Пр",
        date=dt.date(2024, 9, 30),
        hour_number=2,
        value="Н",
        is_pass=True,
    )

    restored = NewGradeNotice.from_dict(json.loads(json.dumps(notice.to_dict())))

    assert restored == notice
    assert restored.lesson_key == "10:2024-09-30:2"


PEER = UserSyncInfo(
    id=2,
    is_authenticated=True,
    edu_user_id=1002,
    group_id=3273,
    group_name="584 ис-3",
    full_name="Петров П.П.",
    language_code="ru",
)


def _group_payload(journal_id: int, students: dict[int, tuple[Lesson, ...]]) -> JournalPayload:
    return JournalPayload(
        journal_id=journal_id,
        name=f"Журнал {journal_id}",
        is_subgroup=False,
        students=tuple(
            StudentGrades(student_id=student_id, lessons=lessons) for student_id, lessons in students.items()
        ),
    )


class NoticeRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[int, list[NewGradeNotice]]] = []

    def __call__(self, user_id: int, notices: Any) -> None:
        self.calls.append((user_id, list(notices)))


async def test_opportunistic_off_does_not_touch_peers(
    sync_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Флаг выключен: чужие оценки не меняются и уведомлений нет (задача 4.2)."""
    monkeypatch.setattr(
        "bot.services.grade_sync.load_group_members",
        AsyncMock(return_value=[USER, PEER]),
    )
    recorder = NoticeRecorder()
    payload = _group_payload(10, {1001: (_lesson(1, "4", number=4),), 1002: (_lesson(2, "4", number=4),)})
    service = _service(FakeCache({10: payload}), [JournalBrief(id=10, name="Журнал 10")], notifier=recorder)

    summary = await service.sync_user(1)

    assert {user_id for user_id, *_ in sync_env["store"]} == {1}
    assert recorder.calls == []
    assert summary.new_grades == 1


async def test_opportunistic_updates_peer_and_notifies_once(
    sync_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Флаг включён: участник группы обновляется тем же журналом и получает уведомление."""
    monkeypatch.setattr(
        "bot.services.grade_sync.load_group_members",
        AsyncMock(return_value=[USER, PEER]),
    )
    # У участника уже была оценка в этом журнале — значит, это не первичный импорт.
    sync_env["store"][(2, 10, 4)] = _store_grade(10, _lesson(4, "3", number=3), user_id=2)
    recorder = NoticeRecorder()
    payload = _group_payload(10, {1001: (_lesson(1, "4", number=4),), 1002: (_lesson(5, "5", number=5),)})
    service = _service(
        FakeCache({10: payload}),
        [JournalBrief(id=10, name="Журнал 10")],
        opportunistic=True,
        notifier=recorder,
    )

    await service.sync_user(1)

    assert (2, 10, 5) in sync_env["store"]
    assert len(recorder.calls) == 1
    user_id, notices = recorder.calls[0]
    assert user_id == 2
    assert [notice.lesson_key for notice in notices] == ["10:2024-09-30:5"]

    # Повторный прогон не создаёт дублей и не уведомляет второй раз.
    await service.sync_user(1)
    assert len(recorder.calls) == 1
    assert len(sync_env["store"]) == 3


async def test_opportunistic_is_silent_on_peer_first_import(
    sync_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Первичный импорт участника сохраняется, но не уведомляет о «новых» оценках."""
    monkeypatch.setattr(
        "bot.services.grade_sync.load_group_members",
        AsyncMock(return_value=[USER, PEER]),
    )
    recorder = NoticeRecorder()
    payload = _group_payload(10, {1001: (_lesson(1, "4", number=4),), 1002: (_lesson(5, "5", number=5),)})
    service = _service(
        FakeCache({10: payload}),
        [JournalBrief(id=10, name="Журнал 10")],
        opportunistic=True,
        notifier=recorder,
    )

    await service.sync_user(1)

    assert (2, 10, 5) in sync_env["store"]
    assert recorder.calls == []


async def test_opportunistic_skips_locked_peer(
    sync_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Занятый sync:lock участника не трогаем: у него идёт своя синхронизация."""
    monkeypatch.setattr(
        "bot.services.grade_sync.load_group_members",
        AsyncMock(return_value=[USER, PEER]),
    )

    @asynccontextmanager
    async def lock(user_id: int):
        yield user_id != PEER.id

    recorder = NoticeRecorder()
    payload = _group_payload(10, {1001: (_lesson(1, "4", number=4),), 1002: (_lesson(5, "5", number=5),)})
    service = _service(
        FakeCache({10: payload}),
        [JournalBrief(id=10, name="Журнал 10")],
        opportunistic=True,
        notifier=recorder,
        user_lock=lock,
    )

    await service.sync_user(1)

    assert (2, 10, 5) not in sync_env["store"]
    assert recorder.calls == []
