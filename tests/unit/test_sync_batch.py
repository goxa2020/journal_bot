"""Задача `sync_all_users`: батч-лок, метрики и алерт админам (задачи 4.3–4.4).

Сеть и PostgreSQL не нужны: `GroupSyncService`, Redis, сессия и Telegram подменяются,
а метрики проверяются через `prometheus_client.REGISTRY`.
"""

from __future__ import annotations
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY

from bot.core.config import settings
from bot.services.group_sync import BatchSummary
from bot.tasks.sync import BATCH_LOCK_TTL, SYNC_ALL_LOCK_KEY, _user_lock, sync_all_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class FakeGroupService:
    """Заменяет `GroupSyncService`: возвращает заранее собранную сводку."""

    summary: BatchSummary | None = None
    error: Exception | None = None
    created: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        FakeGroupService.created.append(kwargs)

    async def sync_all(self) -> BatchSummary:
        if FakeGroupService.error is not None:
            raise FakeGroupService.error
        assert FakeGroupService.summary is not None
        return FakeGroupService.summary


class FakeLock:
    """Запоминает, с какими аргументами брали lokи."""

    def __init__(self, *, acquired: bool = True) -> None:
        self.acquired = acquired
        self.calls: list[tuple[str, int, bool]] = []

    @asynccontextmanager
    async def __call__(self, key: str, ttl: int = 300, *, release: bool = False) -> AsyncIterator[bool]:
        self.calls.append((key, ttl, release))
        yield self.acquired


@pytest.fixture
def batch_env(monkeypatch: pytest.MonkeyPatch):
    """Окружение задачи: свои Redis/сессия/клиент, фейковый сервис и Telegram."""
    FakeGroupService.created = []
    FakeGroupService.error = None
    send = AsyncMock()
    admins = AsyncMock(return_value=[111, 222])

    @asynccontextmanager
    async def redis_context() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    @asynccontextmanager
    async def session_context() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    class ClientContext:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("bot.tasks.sync.GroupSyncService", FakeGroupService)
    monkeypatch.setattr("bot.tasks.sync.task_redis", redis_context)
    monkeypatch.setattr("bot.tasks.sync.task_session", session_context)
    monkeypatch.setattr("bot.tasks.sync.EduTpiClient", ClientContext)
    monkeypatch.setattr("bot.tasks.sync.JournalCache", MagicMock())
    monkeypatch.setattr("bot.tasks.sync.send_telegram_message", send)
    monkeypatch.setattr("bot.tasks.sync.load_admin_ids", admins)
    return {"send": send, "admins": admins}


def _summary(**kwargs: Any) -> BatchSummary:
    values: dict[str, Any] = {
        "groups": 1,
        "users": 2,
        "success": 2,
        "failed": 0,
        "skipped": 0,
        "new_grades": 3,
        "updated_grades": 1,
    }
    values.update(kwargs)
    return BatchSummary(**values)


def _metric(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_locked_batch_returns_skipped_without_error(
    monkeypatch: pytest.MonkeyPatch,
    batch_env: dict[str, Any],
    celery_eager: None,
) -> None:
    """Занятый `sync:all:lock` — `skipped: locked`, сервис не запускается."""
    lock = FakeLock(acquired=False)
    monkeypatch.setattr("bot.tasks.sync.task_lock", lock)
    FakeGroupService.summary = _summary()

    result = sync_all_users.apply(args=()).get()

    assert result["status"] == "skipped"
    assert result["reason"] == "locked"
    assert result["users"] == 0
    assert FakeGroupService.created == []
    assert lock.calls == [(SYNC_ALL_LOCK_KEY, BATCH_LOCK_TTL, True)]


def test_empty_run_is_success_with_zeros(
    monkeypatch: pytest.MonkeyPatch,
    batch_env: dict[str, Any],
    celery_eager: None,
) -> None:
    monkeypatch.setattr("bot.tasks.sync.task_lock", FakeLock())
    FakeGroupService.summary = BatchSummary()

    result = sync_all_users.apply(args=()).get()

    assert result["status"] == "success"
    assert (result["groups"], result["users"], result["success"], result["failed"]) == (0, 0, 0, 0)
    batch_env["send"].assert_not_awaited()


def test_batch_metrics_count_users_statuses_and_duration(
    monkeypatch: pytest.MonkeyPatch,
    batch_env: dict[str, Any],
    celery_eager: None,
) -> None:
    monkeypatch.setattr("bot.tasks.sync.task_lock", FakeLock())
    FakeGroupService.summary = _summary(users=5, success=2, failed=2, skipped=1, new_grades=4)

    before_success = _metric("sync_batch_users_total", {"status": "success"})
    before_failed = _metric("sync_batch_users_total", {"status": "failed"})
    before_skipped = _metric("sync_batch_users_total", {"status": "skipped"})
    before_new = _metric("sync_new_grades_total", {"type": "auto"})
    before_runs = _metric("sync_batch_duration_seconds_count", {})

    sync_all_users.apply(args=()).get()

    assert _metric("sync_batch_users_total", {"status": "success"}) == before_success + 2
    assert _metric("sync_batch_users_total", {"status": "failed"}) == before_failed + 2
    assert _metric("sync_batch_users_total", {"status": "skipped"}) == before_skipped + 1
    assert _metric("sync_new_grades_total", {"type": "auto"}) == before_new + 4
    assert _metric("sync_batch_duration_seconds_count", {}) == before_runs + 1


def test_alert_is_sent_once_per_admin_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
    batch_env: dict[str, Any],
    celery_eager: None,
) -> None:
    """Доля сбоев выше порога — одно сообщение каждому админу, только числа."""
    monkeypatch.setattr("bot.tasks.sync.task_lock", FakeLock())
    monkeypatch.setattr(settings, "SYNC_ALERT_MIN_USERS", 5)
    monkeypatch.setattr(settings, "SYNC_ALERT_FAILURE_RATIO", 0.2)
    FakeGroupService.summary = _summary(groups=2, users=10, success=5, failed=5)

    result = sync_all_users.apply(args=()).get()

    assert result["failed"] == 5
    assert batch_env["send"].await_count == 2
    chat_ids = [call.args[0] for call in batch_env["send"].await_args_list]
    assert chat_ids == [111, 222]
    text = batch_env["send"].await_args_list[0].args[1]
    assert "5" in text
    assert "10" in text
    assert "2" in text


@pytest.mark.parametrize(
    ("users", "failed", "min_users", "ratio"),
    [
        # Доля ниже порога: 1 из 10.
        (10, 1, 5, 0.2),
        # Меньше минимального размера прогона.
        (4, 4, 5, 0.2),
    ],
)
def test_no_alert_below_thresholds(  # noqa: PLR0913, PLR0917 — аргументы из parametrize
    monkeypatch: pytest.MonkeyPatch,
    batch_env: dict[str, Any],
    celery_eager: None,
    users: int,
    failed: int,
    min_users: int,
    ratio: float,
) -> None:
    monkeypatch.setattr("bot.tasks.sync.task_lock", FakeLock())
    monkeypatch.setattr(settings, "SYNC_ALERT_MIN_USERS", min_users)
    monkeypatch.setattr(settings, "SYNC_ALERT_FAILURE_RATIO", ratio)
    FakeGroupService.summary = _summary(users=users, success=users - failed, failed=failed)

    sync_all_users.apply(args=()).get()

    batch_env["send"].assert_not_awaited()


def test_alert_telegram_failure_does_not_fail_the_batch(
    monkeypatch: pytest.MonkeyPatch,
    batch_env: dict[str, Any],
    celery_eager: None,
) -> None:
    """Падение Telegram при алерте не роняет батч: оценки уже сохранены."""
    monkeypatch.setattr("bot.tasks.sync.task_lock", FakeLock())
    monkeypatch.setattr(settings, "SYNC_ALERT_MIN_USERS", 1)
    monkeypatch.setattr(settings, "SYNC_ALERT_FAILURE_RATIO", 0.5)
    FakeGroupService.summary = _summary(groups=1, users=10, success=0, failed=10, status="failed")
    batch_env["send"].side_effect = RuntimeError("telegram down")

    result = sync_all_users.apply(args=()).get()

    assert result["status"] == "failed"
    assert result["failed"] == 10
    assert batch_env["send"].await_count == 2


def test_no_alert_without_admins(
    monkeypatch: pytest.MonkeyPatch,
    batch_env: dict[str, Any],
    celery_eager: None,
) -> None:
    monkeypatch.setattr("bot.tasks.sync.task_lock", FakeLock())
    monkeypatch.setattr(settings, "SYNC_ALERT_MIN_USERS", 1)
    monkeypatch.setattr(settings, "SYNC_ALERT_FAILURE_RATIO", 0.5)
    batch_env["admins"].return_value = []
    FakeGroupService.summary = _summary(users=5, success=0, failed=5)

    sync_all_users.apply(args=()).get()

    batch_env["send"].assert_not_awaited()


async def test_user_lock_key_is_released_after_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-user lock снимается после дифа: иначе ручная синхронизация ждала бы TTL."""
    lock = FakeLock()
    monkeypatch.setattr("bot.tasks.sync.task_lock", lock)

    async with _user_lock(42):
        pass

    assert lock.calls == [("sync:lock:42", 300, True)]
