"""Групповая синхронизация: один запрос к edu-tpi на группу/подгруппу (задачи 4.1–4.5).

Сеть и PostgreSQL не нужны: `fakeredis` вместо Redis, словарь-хранилище вместо БД,
фейковый клиент считает `get_journal`. Именно счётчик запросов и ловит регрессию, если
групповая синхронизация начнёт ходить в edu-tpi за каждого пользователя.
"""

from __future__ import annotations
import datetime as dt
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from bot.core.errors import EduAuthError, EduEmptyJournalError
from bot.database.models import Grade
from bot.database.models.sync_log import SyncStatus, SyncType
from bot.integrations.journal_cache import JournalCache
from bot.integrations.models import EduUser, JournalBrief, JournalPayload, Lesson, StudentGrades, TokenInfo
from bot.services.auth import save_token
from bot.services.grades import GradesService
from bot.services.group_sync import GroupSyncService
from bot.services.users import UserSyncInfo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bot.services.grade_sync import NewGradeNotice

GROUP_ID = 3273
JOURNAL_ID = 10
DATE = dt.date(2024, 9, 30)


def _user(user_id: int, edu_user_id: int) -> UserSyncInfo:
    return UserSyncInfo(
        id=user_id,
        is_authenticated=True,
        edu_user_id=edu_user_id,
        group_id=GROUP_ID,
        group_name="584 ис-3",
        full_name=f"Студентов {user_id}",
        language_code="ru",
    )


def _lesson(hour: int = 1, value: str = "5") -> Lesson:
    number = int(value) if value.isdigit() else None
    return Lesson(
        date=DATE,
        hour_number=hour,
        edu_lesson_id=346734 + hour,
        value=value,
        number_value=number,
        is_mark=number is not None,
        is_pass=number is None and bool(value),
    )


def _payload(
    journal_id: int,
    students: dict[int, tuple[Lesson, ...]],
    *,
    is_subgroup: bool = False,
) -> JournalPayload:
    return JournalPayload(
        journal_id=journal_id,
        name=f"Журнал {journal_id}",
        type="Лек",
        is_subgroup=is_subgroup,
        students=tuple(
            StudentGrades(student_id=student_id, lessons=lessons) for student_id, lessons in students.items()
        ),
    )


class FakeClient:
    """Клиент edu-tpi: отдаёт журналы по токену и считает запросы."""

    def __init__(
        self,
        journals: list[JournalBrief] | dict[str, list[JournalBrief]],
        payloads: dict[tuple[str, int], JournalPayload],
        *,
        list_errors: dict[str, Exception] | None = None,
        journal_errors: dict[tuple[str, int], Exception] | None = None,
    ) -> None:
        self._journals = journals
        self._payloads = payloads
        self._list_errors = list_errors or {}
        self._journal_errors = journal_errors or {}
        #: Все вызовы `get_journal`: (токен, id журнала).
        self.journal_calls: list[tuple[str, int]] = []
        self.list_calls = 0

    async def list_journals(self, token: str, *, year: str, sem: int) -> list[JournalBrief]:
        self.list_calls += 1
        if token in self._list_errors:
            raise self._list_errors[token]
        if isinstance(self._journals, dict):
            return self._journals.get(token, [])
        return self._journals

    async def get_journal(self, token: str, journal_id: int) -> JournalPayload:
        self.journal_calls.append((token, journal_id))
        error = self._journal_errors.get((token, journal_id))
        if error is not None:
            raise error
        return self._payloads[(token, journal_id)]


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


async def _seed_token(redis: fakeredis.aioredis.FakeRedis, member: UserSyncInfo) -> str:
    """Положить в Redis валидный токен: `TokenService` не пойдёт переавторизовываться."""
    token = f"token-{member.edu_user_id}"
    await save_token(
        redis,
        member.id,
        TokenInfo(access_token=token, expires_in_minutes=60, edu_user_id=member.edu_user_id),
        EduUser(user_id=member.edu_user_id or 0, group_id=member.group_id),
    )
    return token


@pytest.fixture
def sync_env(monkeypatch: pytest.MonkeyPatch):
    """Словарь-хранилище оценок и `sync_logs` вместо PostgreSQL."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    store: dict[tuple[int, int, dt.date, int], Grade] = {}
    logs: list[dict[str, Any]] = []

    async def load_lesson_map(_session: Any, user_id: int, journal_id: int) -> dict[tuple[dt.date, int], Grade]:
        return {
            (grade.date, grade.hour_number): grade
            for (stored_user, stored_journal, _date, _hour), grade in store.items()
            if stored_user == user_id and stored_journal == journal_id
        }

    async def insert_lessons(
        _session: Any,
        user_id: int,
        journal_id: int,
        lessons: list[Lesson],
    ) -> int:
        for lesson in lessons:
            store[(user_id, journal_id, lesson.date, lesson.hour_number)] = Grade(
                id=len(store) + 1,
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
        return len(lessons)

    async def write_log(_session: Any, **kwargs: Any) -> None:
        logs.append(kwargs)

    monkeypatch.setattr(GradesService, "load_lesson_map", AsyncMock(side_effect=load_lesson_map))
    monkeypatch.setattr(GradesService, "insert_lessons", AsyncMock(side_effect=insert_lessons))
    monkeypatch.setattr(GradesService, "update_lesson", AsyncMock())
    monkeypatch.setattr("bot.services.grade_sync.upsert_and_link", AsyncMock())
    monkeypatch.setattr("bot.services.group_sync.write_sync_log", AsyncMock(side_effect=write_log))
    return {"session": session, "store": store, "logs": logs}


def _service(
    redis: fakeredis.aioredis.FakeRedis,
    client: FakeClient,
    members: list[UserSyncInfo],
    *,
    notifier: Any = None,
    user_lock: Any = None,
) -> GroupSyncService:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return GroupSyncService(
        session=session,
        client=client,  # type: ignore[arg-type]
        cache=JournalCache(redis, client),  # type: ignore[arg-type]
        redis=redis,
        user_lock=user_lock,
        notifier=notifier,
    )


class Recorder:
    """Записывает поставленные уведомления: (user_id, notice-ы)."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, Sequence[NewGradeNotice]]] = []

    def __call__(self, user_id: int, notices: Sequence[NewGradeNotice]) -> None:
        self.calls.append((user_id, notices))


def _patch_candidates(monkeypatch: pytest.MonkeyPatch, members: list[UserSyncInfo]) -> None:
    monkeypatch.setattr(
        "bot.services.group_sync.load_sync_candidates",
        AsyncMock(return_value=members),
    )


async def test_two_users_one_group_one_journal_is_one_request(
    redis: fakeredis.aioredis.FakeRedis,
    sync_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Критерий 4.5: два пользователя одной группы — ровно один запрос на журнал."""
    first, second = _user(1, 1001), _user(2, 1002)
    _patch_candidates(monkeypatch, [first, second])
    token_first = await _seed_token(redis, first)
    await _seed_token(redis, second)

    payload = _payload(JOURNAL_ID, {1001: (_lesson(),), 1002: (_lesson(2, "4"),)})
    client = FakeClient([JournalBrief(id=JOURNAL_ID, name="Журнал 10")], {(token_first, JOURNAL_ID): payload})
    notifier = Recorder()

    summary = await _service(redis, client, [first, second], notifier=notifier).sync_all()

    assert len(client.journal_calls) == 1
    assert client.journal_calls == [(token_first, JOURNAL_ID)]
    assert client.list_calls == 1
    assert len(sync_env["store"]) == 2
    assert {(user_id, journal_id) for user_id, journal_id, *_ in sync_env["store"]} == {
        (1, JOURNAL_ID),
        (2, JOURNAL_ID),
    }
    assert summary.status == "success"
    assert summary.users == 2
    assert summary.success == 2
    assert summary.failed == 0
    assert summary.new_grades == 2
    assert [user_id for user_id, _ in notifier.calls] == [1, 2]
    assert all(len(notices) == 1 for _, notices in notifier.calls)
    # sync_logs пишутся с sync_type=auto, по записи на пользователя.
    assert [(log["user_id"], log["sync_type"]) for log in sync_env["logs"]] == [
        (1, SyncType.AUTO),
        (2, SyncType.AUTO),
    ]
    assert {log["status"] for log in sync_env["logs"]} == {SyncStatus.SUCCESS}


async def test_two_subgroups_need_one_request_each(
    redis: fakeredis.aioredis.FakeRedis,
    sync_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Разные подгруппы одного журнала — по одному запросу на подгруппу."""
    first, second = _user(1, 1001), _user(2, 1002)
    _patch_candidates(monkeypatch, [first, second])
    token_first = await _seed_token(redis, first)
    token_second = await _seed_token(redis, second)

    client = FakeClient(
        [JournalBrief(id=JOURNAL_ID, name="Журнал 10")],
        {
            (token_first, JOURNAL_ID): _payload(JOURNAL_ID, {1001: (_lesson(),), 1003: ()}, is_subgroup=True),
            (token_second, JOURNAL_ID): _payload(JOURNAL_ID, {1002: (_lesson(),), 1004: ()}, is_subgroup=True),
        },
    )
    notifier = Recorder()

    summary = await _service(redis, client, [first, second], notifier=notifier).sync_all()

    assert sorted(client.journal_calls) == sorted([(token_first, JOURNAL_ID), (token_second, JOURNAL_ID)])
    assert summary.success == 2
    assert summary.failed == 0
    assert len(sync_env["store"]) == 2
    assert sorted(user_id for user_id, _ in notifier.calls) == [1, 2]


async def test_empty_journal_of_foreign_subgroup_is_not_an_error(
    redis: fakeredis.aioredis.FakeRedis,
    sync_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой журнал (чужая подгруппа/архив) пропускается без ошибки."""
    first, second = _user(1, 1001), _user(2, 1002)
    _patch_candidates(monkeypatch, [first, second])
    token_first = await _seed_token(redis, first)
    await _seed_token(redis, second)

    full = _payload(11, {1001: (_lesson(),), 1002: (_lesson(),)})
    client = FakeClient(
        [JournalBrief(id=11, name="Лекция"), JournalBrief(id=12, name="Практика")],
        {(token_first, 11): full},
        journal_errors={(token_first, 12): EduEmptyJournalError("empty")},
    )

    summary = await _service(redis, client, [first, second]).sync_all()

    assert summary.status == "success"
    assert summary.success == 2
    assert summary.failed == 0
    assert summary.errors == []
    assert summary.new_grades == 2


async def test_auth_error_of_one_member_does_not_stop_the_rest(
    redis: fakeredis.aioredis.FakeRedis,
    sync_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка авторизации одного участника — он failed, остальные синхронизируются."""
    first, second = _user(1, 1001), _user(2, 1002)
    _patch_candidates(monkeypatch, [first, second])
    token_first = await _seed_token(redis, first)
    token_second = await _seed_token(redis, second)

    brief = JournalBrief(id=JOURNAL_ID, name="Журнал 10")
    client = FakeClient(
        {token_second: [brief]},
        {(token_second, JOURNAL_ID): _payload(JOURNAL_ID, {1002: (_lesson(),)})},
        list_errors={token_first: EduAuthError("bad token")},
        journal_errors={(token_first, JOURNAL_ID): EduAuthError("bad token")},
    )

    summary = await _service(redis, client, [first, second]).sync_all()

    assert summary.success == 1
    assert summary.failed == 1
    assert "auth" in summary.errors
    assert len(sync_env["store"]) == 1
    assert next(iter(sync_env["store"]))[0] == 2


async def test_repeated_batch_creates_no_duplicates(
    redis: fakeredis.aioredis.FakeRedis,
    sync_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повторный прогон идемпотентен: оценки не дублируются, уведомлений нет."""
    first, second = _user(1, 1001), _user(2, 1002)
    _patch_candidates(monkeypatch, [first, second])
    token_first = await _seed_token(redis, first)
    await _seed_token(redis, second)

    payload = _payload(JOURNAL_ID, {1001: (_lesson(),), 1002: (_lesson(2, "4"),)})
    client = FakeClient([JournalBrief(id=JOURNAL_ID, name="Журнал 10")], {(token_first, JOURNAL_ID): payload})
    notifier = Recorder()
    service = _service(redis, client, [first, second], notifier=notifier)

    first_summary = await service.sync_all()
    second_summary = await service.sync_all()

    assert first_summary.new_grades == 2
    assert second_summary.new_grades == 0
    assert len(sync_env["store"]) == 2
    # Уведомления поставлены только в первом прогоне.
    assert len(notifier.calls) == 2


async def test_locked_user_is_skipped_and_retried_next_run(
    redis: fakeredis.aioredis.FakeRedis,
    sync_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Занятый `sync:lock` участника — skipped, ручная синхронизация не ломается."""
    first, second = _user(1, 1001), _user(2, 1002)
    _patch_candidates(monkeypatch, [first, second])
    token_first = await _seed_token(redis, first)
    await _seed_token(redis, second)

    @asynccontextmanager
    async def fake_lock(user_id: int):
        yield user_id != second.id

    payload = _payload(JOURNAL_ID, {1001: (_lesson(),), 1002: (_lesson(),)})
    client = FakeClient([JournalBrief(id=JOURNAL_ID, name="Журнал 10")], {(token_first, JOURNAL_ID): payload})
    notifier = Recorder()

    summary = await _service(redis, client, [first, second], notifier=notifier, user_lock=fake_lock).sync_all()

    assert summary.success == 1
    assert summary.skipped == 1
    assert summary.failed == 0
    assert {user_id for user_id, *_ in sync_env["store"]} == {1}
    assert [user_id for user_id, _ in notifier.calls] == [1]


async def test_no_candidates_is_success_with_zeros(
    redis: fakeredis.aioredis.FakeRedis,
    sync_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустая БД/нет авторизованных — успех с нулями, без запросов."""
    _patch_candidates(monkeypatch, [])
    client = FakeClient([], {})

    summary = await _service(redis, client, []).sync_all()

    assert summary.status == "success"
    assert (summary.groups, summary.users, summary.success, summary.failed) == (0, 0, 0, 0)
    assert client.journal_calls == []
    assert client.list_calls == 0


async def test_no_progress_marks_remaining_failed(
    redis: fakeredis.aioredis.FakeRedis,
    sync_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если проход не уменьшил `unprocessed`, остаток помечается failed без цикла."""
    first, second = _user(1, 1001), _user(2, 1002)
    _patch_candidates(monkeypatch, [first, second])
    token_first = await _seed_token(redis, first)
    await _seed_token(redis, second)

    payload = _payload(JOURNAL_ID, {999: (_lesson(),)})
    client = FakeClient([JournalBrief(id=JOURNAL_ID, name="Журнал 10")], {(token_first, JOURNAL_ID): payload})

    summary = await _service(redis, client, [first, second]).sync_all()

    assert summary.status == "failed"
    assert summary.failed == 2
    assert summary.success == 0
    assert "unprocessed" in summary.errors
