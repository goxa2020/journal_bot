"""Задачи уведомлений: отправка, ночная очередь, ошибки Telegram (задачи 3.2, 3.4).

Telegram и брокер подменены: задача проверяется в том же процессе, без сети.
Ночная очередь живёт в `fakeredis`.
"""

from __future__ import annotations
import asyncio
import datetime as dt
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from fakeredis import FakeServer

from bot.core.config import TIMEZONE
from bot.core.errors import PermanentError, RetryableError
from bot.services.grade_sync import NewGradeNotice
from bot.services.notifications import night_key, night_scheduled_key, sent_key
from bot.services.users import NotificationSettings
from bot.tasks.notify import _send_night_batch, notify_new_grades, send_grade_notification, send_night_batch

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from redis.asyncio import Redis

NIGHT = dt.datetime(2026, 11, 22, 23, 0, tzinfo=TIMEZONE)
DAY = dt.datetime(2026, 11, 22, 12, 0, tzinfo=TIMEZONE)


def _notice(hour: int = 1, value: str = "5") -> NewGradeNotice:
    return NewGradeNotice(
        journal_id=10,
        journal_name="Программирование",
        journal_type="Лек",
        date=dt.date(2026, 11, 20),
        hour_number=hour,
        value=value,
        number_value=5 if value.isdigit() else None,
        is_mark=value.isdigit(),
        is_pass=not value.isdigit(),
    )


def _settings(*, enabled: bool = True, morning_enabled: bool = True) -> NotificationSettings:
    return NotificationSettings(
        enabled=enabled,
        morning_enabled=morning_enabled,
        morning_time=dt.time(8, 0),
        language_code="ru",
    )


def _install_env(
    monkeypatch: pytest.MonkeyPatch,
    redis: Redis,
    *,
    settings: NotificationSettings | None = None,
    send: AsyncMock | None = None,
) -> AsyncMock:
    """Подменить Redis, сессию, настройки и отправку внутри `bot.tasks.notify`."""
    sender = send or AsyncMock()
    settings_loader = AsyncMock(return_value=settings or _settings())

    @asynccontextmanager
    async def redis_context() -> AsyncIterator[Redis]:
        yield redis

    @asynccontextmanager
    async def session_context() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    monkeypatch.setattr("bot.tasks.notify.task_redis", redis_context)
    monkeypatch.setattr("bot.tasks.notify.task_session", session_context)
    monkeypatch.setattr("bot.tasks.notify.send_telegram_message", sender)
    monkeypatch.setattr("bot.services.notifications.load_notification_settings", settings_loader)
    return sender


def _patch_now(monkeypatch: pytest.MonkeyPatch, moment: dt.datetime) -> None:
    monkeypatch.setattr("bot.services.notifications.now", lambda: moment)


def _sample(name: str, labels: dict[str, str]) -> float:
    from prometheus_client import REGISTRY  # noqa: PLC0415 — нужен только в тестах метрик

    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_immediate_notification_is_one_message_and_marks_lessons(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    send = _install_env(monkeypatch, fake_redis)
    _patch_now(monkeypatch, DAY)
    notices = [_notice(hour=1), _notice(hour=2, value="4")]

    result = await notify_new_grades(1, notices, manual=True)

    assert result == {"kind": "immediate", "status": "sent", "count": 2}
    send.assert_awaited_once()
    text = send.await_args.args[1]
    assert "📊 Новые оценки" in text
    assert len(text.splitlines()) == 3
    assert all([await fake_redis.exists(sent_key(1, notice.lesson_key)) for notice in notices])


async def test_repeat_of_the_same_notice_is_skipped(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    send = _install_env(monkeypatch, fake_redis)
    _patch_now(monkeypatch, DAY)
    notice = _notice()

    first = await notify_new_grades(1, [notice], manual=True)
    second = await notify_new_grades(1, [notice], manual=True)

    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    send.assert_awaited_once()


async def test_disabled_notifications_send_nothing(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    send = _install_env(monkeypatch, fake_redis, settings=_settings(enabled=False))
    _patch_now(monkeypatch, DAY)

    result = await notify_new_grades(1, [_notice()])

    assert result["status"] == "skipped"
    send.assert_not_awaited()


async def test_night_batch_is_queued_once_and_scheduled_for_morning(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    send = _install_env(monkeypatch, fake_redis)
    _patch_now(monkeypatch, NIGHT)
    scheduler = MagicMock()
    monkeypatch.setattr("bot.tasks.notify.send_night_batch", scheduler)

    result = await notify_new_grades(1, [_notice()])

    assert result == {"kind": "night", "status": "queued", "count": 1}
    send.assert_not_awaited()
    assert len(await fake_redis.lrange(night_key(1), 0, -1)) == 1
    assert await fake_redis.exists(night_scheduled_key(1)) == 1
    scheduler.apply_async.assert_called_once_with(args=[1], eta=dt.datetime(2026, 11, 23, 8, 0, tzinfo=TIMEZONE))


async def test_second_night_sync_does_not_schedule_another_batch(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    _install_env(monkeypatch, fake_redis)
    _patch_now(monkeypatch, NIGHT)
    scheduler = MagicMock()
    monkeypatch.setattr("bot.tasks.notify.send_night_batch", scheduler)

    await notify_new_grades(1, [_notice(hour=1)])
    await notify_new_grades(1, [_notice(hour=2)])

    scheduler.apply_async.assert_called_once()
    assert len(await fake_redis.lrange(night_key(1), 0, -1)) == 2


async def test_night_without_accumulation_sends_immediately(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    send = _install_env(monkeypatch, fake_redis, settings=_settings(morning_enabled=False))
    _patch_now(monkeypatch, NIGHT)

    result = await notify_new_grades(1, [_notice()])

    assert result["status"] == "sent"
    send.assert_awaited_once()


async def test_manual_sync_at_night_sends_immediately(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    send = _install_env(monkeypatch, fake_redis)
    _patch_now(monkeypatch, NIGHT)

    result = await notify_new_grades(1, [_notice()], manual=True)

    assert result["status"] == "sent"
    send.assert_awaited_once()
    assert await fake_redis.exists(night_key(1)) == 0


async def test_night_batch_sends_the_list_and_clears_keys(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    send = _install_env(monkeypatch, fake_redis)
    _patch_now(monkeypatch, dt.datetime(2026, 11, 23, 8, 0, tzinfo=TIMEZONE))
    await fake_redis.rpush(
        night_key(1),
        json.dumps(_notice(hour=1).to_dict(), ensure_ascii=False),
        json.dumps(_notice(hour=2, value="4").to_dict(), ensure_ascii=False),
    )
    await fake_redis.set(night_scheduled_key(1), "1")

    result = await _send_night_batch(1)

    assert result == {"kind": "night", "status": "sent", "count": 2}
    send.assert_awaited_once()
    assert len(send.await_args.args[1].splitlines()) == 3
    assert await fake_redis.exists(night_key(1)) == 0
    assert await fake_redis.exists(night_scheduled_key(1)) == 0


async def test_empty_night_batch_is_skipped(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    send = _install_env(monkeypatch, fake_redis)

    result = await _send_night_batch(1)

    assert result["status"] == "skipped"
    send.assert_not_awaited()


async def test_repeated_night_batch_does_not_resend(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    send = _install_env(monkeypatch, fake_redis)
    _patch_now(monkeypatch, dt.datetime(2026, 11, 23, 8, 0, tzinfo=TIMEZONE))
    await fake_redis.rpush(night_key(1), json.dumps(_notice().to_dict(), ensure_ascii=False))

    first = await _send_night_batch(1)
    second = await _send_night_batch(1)

    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    send.assert_awaited_once()


async def test_night_batch_restores_the_list_when_send_fails(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    send = _install_env(monkeypatch, fake_redis, send=AsyncMock(side_effect=RuntimeError("network")))
    _patch_now(monkeypatch, dt.datetime(2026, 11, 23, 8, 0, tzinfo=TIMEZONE))
    await fake_redis.rpush(night_key(1), json.dumps(_notice().to_dict(), ensure_ascii=False))

    with pytest.raises(RetryableError):
        await _send_night_batch(1)

    send.assert_awaited_once()
    assert len(await fake_redis.lrange(night_key(1), 0, -1)) == 1


async def test_forbidden_disables_notifications_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    forbidden = TelegramForbiddenError(MagicMock(), "Forbidden: bot was blocked by the user")
    _install_env(monkeypatch, fake_redis, send=AsyncMock(side_effect=forbidden))
    _patch_now(monkeypatch, DAY)
    setter = AsyncMock()
    monkeypatch.setattr("bot.services.notifications.set_notification_enabled", setter)
    notice = _notice()

    result = await notify_new_grades(1, [notice], manual=True)

    assert result == {"kind": "immediate", "status": "blocked", "count": 0}
    assert setter.await_args.kwargs["enabled"] is False
    assert await fake_redis.exists(sent_key(1, notice.lesson_key)) == 0


async def test_retry_after_waits_and_sends_once(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    retry_after = TelegramRetryAfter(MagicMock(), "Too Many Requests", 5)
    send = _install_env(monkeypatch, fake_redis, send=AsyncMock(side_effect=[retry_after, None]))
    _patch_now(monkeypatch, DAY)
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    result = await notify_new_grades(1, [_notice()], manual=True)

    assert result["status"] == "sent"
    assert send.await_count == 2
    sleep.assert_awaited_once_with(5)


async def test_second_retry_after_is_retryable(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    retry_after = TelegramRetryAfter(MagicMock(), "Too Many Requests", 5)
    _install_env(monkeypatch, fake_redis, send=AsyncMock(side_effect=[retry_after, retry_after]))
    _patch_now(monkeypatch, DAY)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    notice = _notice()

    with pytest.raises(RetryableError):
        await notify_new_grades(1, [notice], manual=True)

    assert await fake_redis.exists(sent_key(1, notice.lesson_key)) == 0


async def test_network_error_raises_retryable_and_unmarks(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    _install_env(monkeypatch, fake_redis, send=AsyncMock(side_effect=RuntimeError("network")))
    _patch_now(monkeypatch, DAY)
    notice = _notice()

    with pytest.raises(RetryableError):
        await notify_new_grades(1, [notice], manual=True)

    assert await fake_redis.exists(sent_key(1, notice.lesson_key)) == 0


async def test_blocked_user_does_not_break_another_user(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    forbidden = TelegramForbiddenError(MagicMock(), "Forbidden: bot was blocked by the user")
    send = _install_env(monkeypatch, fake_redis, send=AsyncMock(side_effect=[forbidden, None]))
    _patch_now(monkeypatch, DAY)
    monkeypatch.setattr("bot.services.notifications.set_notification_enabled", AsyncMock())

    first = await notify_new_grades(1, [_notice()], manual=True)
    second = await notify_new_grades(2, [_notice()], manual=True)

    assert first["status"] == "blocked"
    assert second["status"] == "sent"
    assert send.await_count == 2


async def test_metrics_count_sent_skipped_blocked(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, DAY)
    sent_labels = {"kind": "immediate", "status": "sent"}
    skipped_labels = {"kind": "immediate", "status": "skipped"}
    blocked_labels = {"kind": "immediate", "status": "blocked"}
    before = {
        name: _sample("notifications_total", labels)
        for name, labels in (
            ("sent", sent_labels),
            ("skipped", skipped_labels),
            ("blocked", blocked_labels),
        )
    }

    _install_env(monkeypatch, fake_redis)
    await notify_new_grades(1, [_notice()], manual=True)
    await notify_new_grades(1, [_notice()], manual=True)

    forbidden = TelegramForbiddenError(MagicMock(), "Forbidden")
    monkeypatch.setattr("bot.tasks.notify.send_telegram_message", AsyncMock(side_effect=forbidden))
    monkeypatch.setattr("bot.services.notifications.set_notification_enabled", AsyncMock())
    await notify_new_grades(2, [_notice(hour=5)], manual=True)

    assert _sample("notifications_total", sent_labels) == before["sent"] + 1
    assert _sample("notifications_total", skipped_labels) == before["skipped"] + 1
    assert _sample("notifications_total", blocked_labels) == before["blocked"] + 1


async def test_analytics_failure_does_not_block_the_message(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    send = _install_env(monkeypatch, fake_redis)
    _patch_now(monkeypatch, DAY)
    broken = MagicMock()
    broken.log_event = AsyncMock(side_effect=RuntimeError("analytics down"))
    monkeypatch.setattr("bot.services.analytics.logger", broken)

    result = await notify_new_grades(1, [_notice()], manual=True)

    assert result["status"] == "sent"
    send.assert_awaited_once()
    broken.log_event.assert_awaited_once()


async def test_analytics_without_key_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.services.analytics import track_worker_event  # noqa: PLC0415

    monkeypatch.setattr("bot.services.analytics.logger", None)

    await track_worker_event(1, "New Grade")


# --- Celery-обёртки (eager): повтор задачи не дублирует сообщение --------------------


@asynccontextmanager
async def _server_redis(server: FakeServer) -> AsyncIterator[Redis]:
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


def _install_server_env(
    monkeypatch: pytest.MonkeyPatch,
    server: FakeServer,
    *,
    send: AsyncMock | None = None,
) -> AsyncMock:
    sender = send or AsyncMock()

    @asynccontextmanager
    async def redis_context() -> AsyncIterator[Redis]:
        async with _server_redis(server) as client:
            yield client

    @asynccontextmanager
    async def session_context() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    monkeypatch.setattr("bot.tasks.notify.task_redis", redis_context)
    monkeypatch.setattr("bot.tasks.notify.task_session", session_context)
    monkeypatch.setattr("bot.tasks.notify.send_telegram_message", sender)
    monkeypatch.setattr("bot.services.notifications.load_notification_settings", AsyncMock(return_value=_settings()))
    monkeypatch.setattr("bot.services.notifications.now", lambda: DAY)
    return sender


def test_grade_notification_task_is_idempotent_in_eager_mode(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    server = FakeServer()
    send = _install_server_env(monkeypatch, server)

    first = send_grade_notification.apply(args=(1, [_notice().to_dict()])).get()
    second = send_grade_notification.apply(args=(1, [_notice().to_dict()])).get()

    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    send.assert_awaited_once()


def test_night_batch_task_sends_once_in_eager_mode(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    server = FakeServer()
    send = _install_server_env(monkeypatch, server)

    async def seed() -> None:
        async with _server_redis(server) as client:
            await client.rpush(night_key(1), json.dumps(_notice().to_dict(), ensure_ascii=False))

    asyncio.run(seed())

    first = send_night_batch.apply(args=(1,)).get()
    second = send_night_batch.apply(args=(1,)).get()

    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    send.assert_awaited_once()


def test_bad_payload_is_permanent_error(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    server = FakeServer()
    _install_server_env(monkeypatch, server)

    with pytest.raises(PermanentError, match="Некорректные данные уведомления"):
        send_grade_notification.apply(args=(1, [{"journal_id": "oops"}])).get()
