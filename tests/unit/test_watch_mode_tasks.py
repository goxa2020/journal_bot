"""Задачи режима ожидания: цикл проверки и уборка (задачи 5.2–5.3)."""

from __future__ import annotations
import datetime as dt
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import MagicMock

from bot.database.models.sync_log import SyncStatus, SyncType
from bot.integrations.journal_cache import JournalCache
from bot.integrations.models import JournalPayload, Lesson, StudentGrades
from bot.services.grade_sync import NewGradeNotice, SyncSummary
from bot.tasks.service import _run_watch_cleanup
from bot.tasks.sync import _run_watch_cycle

if TYPE_CHECKING:
    import pytest

# ── Цикл `sync_watch_mode_users` ────────────────────────────────────────────


class FakeWatch:
    """Сервис режима: отдаёт заданных ожидающих и запоминает отметки о проверке."""

    instances: ClassVar[list[FakeWatch]] = []
    user_ids: ClassVar[list[int]] = [1, 2]

    def __init__(self, **_kwargs: Any) -> None:
        self.synced: list[int] = []
        self.count = 0
        FakeWatch.instances.append(self)

    async def active_user_ids(self) -> list[int]:
        return list(FakeWatch.user_ids)

    async def mark_synced(self, user_ids: list[int]) -> None:
        self.synced = list(user_ids)

    async def count_active(self) -> int:
        return len(self.synced)


def _summary(user_id: int, *, notices: int = 0) -> SyncSummary:
    summary = SyncSummary(user_id=user_id, sync_type=SyncType.WATCH_MODE, status=SyncStatus.SUCCESS)
    summary.new_grades = notices
    summary.new_notices = [
        NewGradeNotice(
            journal_id=10,
            journal_name="Журнал 10",
            journal_type="Лек",
            date=dt.date(2024, 9, 30),
            hour_number=hour,
            value="4",
            number_value=4,
            is_mark=True,
        )
        for hour in range(1, notices + 1)
    ]
    return summary


@asynccontextmanager
async def _lock(_key: str, _ttl: int = 300, **_kwargs: Any):
    yield True


@asynccontextmanager
async def _locked(_key: str, _ttl: int = 300, **_kwargs: Any):
    yield False


@asynccontextmanager
async def _redis():
    yield MagicMock()


@asynccontextmanager
async def _session():
    yield MagicMock()


def _install(monkeypatch: pytest.MonkeyPatch, *, locked: bool = False) -> MagicMock:
    FakeWatch.instances = []
    FakeWatch.user_ids = [1, 2]
    notify = MagicMock()
    gauge = MagicMock()
    monkeypatch.setattr("bot.tasks.sync.task_lock", _locked if locked else _lock)
    monkeypatch.setattr("bot.tasks.sync.task_redis", _redis)
    monkeypatch.setattr("bot.tasks.sync.task_session", _session)
    monkeypatch.setattr("bot.tasks.sync.WatchModeService", FakeWatch)
    monkeypatch.setattr("bot.tasks.sync._schedule_notification", notify)
    monkeypatch.setattr("bot.tasks.sync.set_active_watch_users", gauge)
    return notify


async def test_cycle_syncs_waiting_users_and_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    notify = _install(monkeypatch)
    calls: list[int] = []

    async def run_sync(user_id: int, *, sync_type: SyncType):
        calls.append(user_id)
        assert sync_type is SyncType.WATCH_MODE
        return _summary(user_id, notices=1 if user_id == 1 else 0), None, "ru"

    monkeypatch.setattr("bot.tasks.sync._run_sync", run_sync)

    result = await _run_watch_cycle()

    assert result["status"] == "ok"
    assert result["users"] == 2
    assert result["new_grades"] == 1
    assert result["errors"] == 0
    assert calls == [1, 2]
    # Уведомление поставлено только по тому пользователю, у кого есть новые оценки.
    assert notify.call_count == 1
    assert notify.call_args.args[0] == 1
    assert FakeWatch.instances[0].synced == [1, 2]


async def test_cycle_survives_user_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)

    async def run_sync(user_id: int, *, sync_type: SyncType):
        _ = sync_type
        if user_id == 1:
            message = "журнал недоступен"
            raise RuntimeError(message)
        return _summary(user_id), None, "ru"

    monkeypatch.setattr("bot.tasks.sync._run_sync", run_sync)

    result = await _run_watch_cycle()

    assert result["status"] == "ok"
    assert result["users"] == 2
    assert result["errors"] == 1


async def test_cycle_skips_locked_user_without_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)

    async def run_sync(_user_id: int, *, sync_type: SyncType):
        _ = sync_type
        return None, "locked", "ru"

    monkeypatch.setattr("bot.tasks.sync._run_sync", run_sync)

    result = await _run_watch_cycle()

    assert result["users"] == 2
    assert result["errors"] == 0


async def test_cycle_does_nothing_when_previous_still_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, locked=True)
    called = MagicMock()

    async def run_sync(*_args: Any, **_kwargs: Any):
        called()
        return _summary(1), None, "ru"

    monkeypatch.setattr("bot.tasks.sync._run_sync", run_sync)

    result = await _run_watch_cycle()

    assert result["status"] == "skipped"
    assert result["reason"] == "locked"
    assert called.call_count == 0


async def test_group_peers_share_one_http_request(fake_redis) -> None:
    """Один запрос на журнал за цикл: двое студентов группы, кеш общий.

    Цикл создаёт сервис кеша на каждого пользователя, но ключи журнала лежат в Redis,
    поэтому второй студент той же группы читает первый ответ, а не идёт в edu-tpi.
    """

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def get_journal(self, _token: str, _journal_id: int) -> JournalPayload:
            self.calls += 1
            lessons = (
                Lesson(
                    date=dt.date(2024, 9, 30),
                    hour_number=1,
                    edu_lesson_id=346734,
                    value="4",
                    number_value=4,
                    is_mark=True,
                ),
            )
            return JournalPayload(
                journal_id=27919,
                name="Программирование",
                teacher_name="Преподавателев П.П.",
                type="Лек",
                year="2024-2025",
                is_subgroup=False,
                students=(
                    StudentGrades(student_id=1001, lessons=lessons),
                    StudentGrades(student_id=1002, lessons=lessons),
                ),
                legend={"Н": "Студент отсутствовал"},
            )

    client = FakeClient()
    first = JournalCache(fake_redis, client)  # type: ignore[arg-type]
    second = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    await first.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1001)
    await second.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1002)

    assert client.calls == 1


# ── Уборка `cleanup_expired_watch_mode` ─────────────────────────────────────


class FakeCleanupWatch(FakeWatch):
    cleaned = 0

    async def expire_stale(self) -> int:
        return self.cleaned


async def test_cleanup_removes_expired_and_updates_gauge(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeCleanupWatch.instances = []
    FakeCleanupWatch.cleaned = 2
    FakeCleanupWatch.user_ids = []
    gauge = MagicMock()
    monkeypatch.setattr("bot.tasks.service.task_redis", _redis)
    monkeypatch.setattr("bot.tasks.service.task_session", _session)
    monkeypatch.setattr("bot.tasks.service.WatchModeService", FakeCleanupWatch)
    monkeypatch.setattr("bot.tasks.service.set_active_watch_users", gauge)

    result = await _run_watch_cleanup()

    assert result == {"cleaned": 2, "active": 0}
    gauge.assert_called_once_with(0)
