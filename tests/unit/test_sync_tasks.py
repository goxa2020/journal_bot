"""Задачи синхронизации в eager-режиме (задача 2.6)."""

from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from celery.exceptions import Retry

from bot.core.errors import EduAuthError, EduUnavailableError, ParseError, PermanentError
from bot.database.models.sync_log import SyncStatus, SyncType
from bot.services.grade_sync import JournalSyncResult, SyncSummary
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

    @asynccontextmanager
    async def lock_context(_key: str, _ttl: int = 300):
        yield not locked

    @asynccontextmanager
    async def redis_context():
        yield MagicMock()

    @asynccontextmanager
    async def session_context():
        yield MagicMock()

    monkeypatch.setattr("bot.tasks.sync.task_lock", lock_context)
    monkeypatch.setattr("bot.tasks.sync.task_redis", redis_context)
    monkeypatch.setattr("bot.tasks.sync.task_session", session_context)
    monkeypatch.setattr("bot.tasks.sync.EduTpiClient", FakeClientContext)
    monkeypatch.setattr("bot.tasks.sync.JournalCache", MagicMock())
    monkeypatch.setattr("bot.tasks.sync.TokenService", MagicMock())
    monkeypatch.setattr("bot.tasks.sync.GradeSyncService", lambda **_kwargs: service)
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
