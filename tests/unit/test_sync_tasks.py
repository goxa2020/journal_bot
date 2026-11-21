"""Задачи синхронизации в eager-режиме (задача 2.6)."""

from __future__ import annotations
import datetime as dt
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from celery.exceptions import Retry
from prometheus_client import REGISTRY

from bot.core.config import settings
from bot.core.errors import EduAuthError, EduUnavailableError, ParseError, PermanentError
from bot.database.models.sync_log import SyncStatus, SyncType
from bot.services.grade_sync import JournalSyncResult, NewGradeNotice, SyncSummary
from bot.services.users import UserSyncInfo
from bot.tasks.sync import sync_user_after_login, sync_user_manual

USER = UserSyncInfo(
    id=1,
    is_authenticated=True,
    edu_user_id=1001,
    group_id=3273,
    group_name="584 ис-3",
    full_name="Студентов С.С.",
    language_code="ru",
)


class FakeSyncService:
    def __init__(self, *, summary: SyncSummary | None = None, error: Exception | None = None) -> None:
        self.summary = summary
        self.error = error
        self.calls = 0
        #: Аргументы, с которыми сервис создали в задаче (проверка флага 4.2).
        self.init_kwargs: list[dict[str, Any]] = []

    async def sync_user(self, _user_id: int) -> SyncSummary:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.summary is not None
        return self.summary


class FakeClientContext:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _install_environment(monkeypatch: pytest.MonkeyPatch, service: FakeSyncService, *, locked: bool = False):
    send = AsyncMock()
    service.init_kwargs = []

    @asynccontextmanager
    async def lock_context(_key: str, _ttl: int = 300, **_kwargs: Any):
        yield not locked

    @asynccontextmanager
    async def redis_context():
        yield MagicMock()

    @asynccontextmanager
    async def session_context():
        yield MagicMock()

    def service_factory(**kwargs: Any) -> FakeSyncService:
        service.init_kwargs.append(kwargs)
        return service

    monkeypatch.setattr("bot.tasks.sync.task_lock", lock_context)
    monkeypatch.setattr("bot.tasks.sync.task_redis", redis_context)
    monkeypatch.setattr("bot.tasks.sync.task_session", session_context)
    monkeypatch.setattr("bot.tasks.sync.EduTpiClient", FakeClientContext)
    monkeypatch.setattr("bot.tasks.sync.JournalCache", MagicMock())
    monkeypatch.setattr("bot.tasks.sync.TokenService", MagicMock())
    monkeypatch.setattr("bot.tasks.sync.GradeSyncService", service_factory)
    monkeypatch.setattr("bot.tasks.sync.send_telegram_message", send)
    monkeypatch.setattr("bot.tasks.sync.load_user_sync_info", AsyncMock(return_value=USER))
    return send


def _summary() -> SyncSummary:
    return SyncSummary(
        user_id=1,
        sync_type=SyncType.MANUAL,
        status=SyncStatus.SUCCESS,
        new_grades=2,
        updated_grades=0,
        journals=[JournalSyncResult(journal_id=10, name="Журнал 10", new_grades=2)],
        language_code="ru",
    )


def _notified_summary() -> SyncSummary:
    summary = _summary()
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
        for hour in (1, 2)
    ]
    return summary


def _metric(sync_type: str) -> float:
    return REGISTRY.get_sample_value("sync_new_grades_total", {"type": sync_type}) or 0.0


def test_manual_sync_sends_notification_instead_of_summary(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    service = FakeSyncService(summary=_notified_summary())
    send = _install_environment(monkeypatch, service)
    notify = AsyncMock(return_value={"kind": "immediate", "status": "sent", "count": 2})
    monkeypatch.setattr("bot.tasks.sync.notify_new_grades", notify)

    result = sync_user_manual.apply(args=(1,)).get()

    notify.assert_awaited_once()
    assert notify.await_args.kwargs["manual"] is True
    # Одно сообщение: сводка не отправляется, если ушло уведомление.
    send.assert_not_awaited()
    assert result["new_notices"] == 2


def test_manual_sync_falls_back_to_summary_when_notifications_are_off(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    service = FakeSyncService(summary=_notified_summary())
    send = _install_environment(monkeypatch, service)
    monkeypatch.setattr(
        "bot.tasks.sync.notify_new_grades",
        AsyncMock(return_value={"kind": "none", "status": "skipped"}),
    )

    sync_user_manual.apply(args=(1,)).get()

    send.assert_awaited_once()
    assert "Синхронизация завершена" in send.await_args.args[1]


def test_manual_sync_does_not_send_summary_when_the_bot_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    service = FakeSyncService(summary=_notified_summary())
    send = _install_environment(monkeypatch, service)
    monkeypatch.setattr(
        "bot.tasks.sync.notify_new_grades",
        AsyncMock(return_value={"kind": "immediate", "status": "blocked"}),
    )

    sync_user_manual.apply(args=(1,)).get()

    send.assert_not_awaited()


def test_after_login_never_notifies(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(summary=_notified_summary())
    send = _install_environment(monkeypatch, service)
    notify = AsyncMock()
    monkeypatch.setattr("bot.tasks.sync.notify_new_grades", notify)

    sync_user_after_login.apply(args=(1,)).get()

    notify.assert_not_awaited()
    send.assert_not_awaited()


def test_manual_sync_counts_new_grades(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(summary=_summary())
    _install_environment(monkeypatch, service)
    before = _metric("manual")

    sync_user_manual.apply(args=(1,)).get()

    assert _metric("manual") == before + 2


def test_after_login_counts_new_grades_as_auto(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(summary=_summary())
    _install_environment(monkeypatch, service)
    before = _metric("auto")

    sync_user_after_login.apply(args=(1,)).get()

    assert _metric("auto") == before + 2


def test_manual_sync_sends_summary(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(summary=_summary())
    send = _install_environment(monkeypatch, service)

    result = sync_user_manual.apply(args=(1,)).get()

    assert result["new_grades"] == 2
    assert service.calls == 1
    send.assert_awaited_once()
    message = send.await_args.args[1]
    assert "Синхронизация завершена" in message
    assert "2" in message


def test_manual_sync_skips_when_locked(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(summary=_summary())
    send = _install_environment(monkeypatch, service, locked=True)

    result = sync_user_manual.apply(args=(1,)).get()

    assert result == {"status": "skipped", "reason": "locked"}
    assert service.calls == 0
    # Короткое сообщение «уже идёт» отправляется, ошибки нет.
    send.assert_awaited_once()
    assert "уже идёт" in send.await_args.args[1]


def test_manual_sync_maps_unavailable_to_retry(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(error=EduUnavailableError("down"))
    send = _install_environment(monkeypatch, service)

    with pytest.raises(Retry):
        sync_user_manual.apply(args=(1,)).get()

    # До исчерпания повторов «недоступен» не шлём — следующая попытка может успеть.
    send.assert_not_awaited()


def test_manual_sync_maps_parse_error_to_permanent(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(error=ParseError("schema"))
    send = _install_environment(monkeypatch, service)

    with pytest.raises(PermanentError):
        sync_user_manual.apply(args=(1,)).get()

    send.assert_awaited_once()
    assert "разобрать" in send.await_args.args[1]


def test_manual_sync_maps_auth_error_to_permanent(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(error=EduAuthError("bad"))
    send = _install_environment(monkeypatch, service)

    with pytest.raises(PermanentError):
        sync_user_manual.apply(args=(1,)).get()

    send.assert_awaited_once()
    assert "/start" in send.await_args.args[1]


def test_after_login_does_not_send_success_message(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(summary=_summary())
    send = _install_environment(monkeypatch, service)

    result = sync_user_after_login.apply(args=(1,)).get()

    assert result["status"] == "success"
    send.assert_not_awaited()


def test_after_login_unavailable_is_retried(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    service = FakeSyncService(error=EduUnavailableError("down"))
    _install_environment(monkeypatch, service)

    with pytest.raises(Retry):
        sync_user_after_login.apply(args=(1,)).get()


@pytest.mark.parametrize("flag", [True, False])
def test_manual_sync_passes_opportunistic_flag(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
    flag: bool,
) -> None:
    """Оппортунистическая часть включается только флагом и только для ручной задачи."""
    service = FakeSyncService(summary=_summary())
    _install_environment(monkeypatch, service)
    monkeypatch.setattr(settings, "SYNC_OPPORTUNISTIC", flag)

    sync_user_manual.apply(args=(1,)).get()

    kwargs = service.init_kwargs[-1]
    assert kwargs["opportunistic"] is flag
    assert callable(kwargs["notifier"])
    assert callable(kwargs["user_lock"])


def test_after_login_never_enables_opportunistic(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    """Первичный импорт после входа флаг не применяет — иначе залп «новых» оценок."""
    service = FakeSyncService(summary=_summary())
    _install_environment(monkeypatch, service)
    monkeypatch.setattr(settings, "SYNC_OPPORTUNISTIC", True)

    sync_user_after_login.apply(args=(1,)).get()

    assert service.init_kwargs[-1]["opportunistic"] is False
