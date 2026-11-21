"""`/sync` и кнопка «Обновить» (задача 2.7)."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.callback.sync import update_callback
from bot.handlers.message.sync import request_manual_sync, sync_command
from bot.tasks.sync import sync_user_manual


@pytest.fixture
def delay(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(sync_user_manual, "delay", mock)
    return mock


async def test_request_sync_enqueues_once(fake_redis, delay: MagicMock) -> None:
    assert await request_manual_sync(1, fake_redis) is True
    assert await request_manual_sync(1, fake_redis) is False

    delay.assert_called_once_with(1)


async def test_request_sync_returns_false_when_lock_is_taken(fake_redis, delay: MagicMock) -> None:
    await fake_redis.set("sync:lock:1", "1", ex=300)

    assert await request_manual_sync(1, fake_redis) is False
    delay.assert_not_called()


async def test_request_sync_releases_queue_key_when_enqueue_fails(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(sync_user_manual, "delay", MagicMock(side_effect=RuntimeError("broker down")))

    with pytest.raises(RuntimeError):
        await request_manual_sync(1, fake_redis)

    assert await fake_redis.exists("sync:queued:1") == 0


async def test_sync_command_for_unauthorized_user_does_not_enqueue(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
    delay: MagicMock,
    ru_locale,
) -> None:
    message = MagicMock()
    message.from_user.id = 1
    message.answer = AsyncMock()
    monkeypatch.setattr("bot.handlers.message.sync.is_authorized", AsyncMock(return_value=False))
    monkeypatch.setattr("bot.handlers.message.sync.get_main_menu", AsyncMock(return_value="меню"))
    monkeypatch.setattr("bot.handlers.message.sync.get_main_menu_keyboard", AsyncMock(return_value=None))

    await sync_command(message, AsyncMock())

    delay.assert_not_called()
    message.answer.assert_awaited_once()
    assert "/start" in message.answer.await_args.args[0]


async def test_sync_command_for_authorized_user_enqueues_and_answers(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
    delay: MagicMock,
    ru_locale,
) -> None:
    message = MagicMock()
    message.from_user.id = 1
    message.answer = AsyncMock()
    monkeypatch.setattr("bot.handlers.message.sync.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr("bot.handlers.message.sync.get_redis_client", lambda: fake_redis)

    await sync_command(message, AsyncMock())

    delay.assert_called_once_with(1)
    message.answer.assert_awaited_once()
    assert "Синхронизация запущена" in message.answer.await_args.args[0]


async def test_update_callback_does_not_duplicate_tasks(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
    delay: MagicMock,
    ru_locale,
) -> None:
    monkeypatch.setattr("bot.handlers.callback.sync.Message", MagicMock)
    callback = MagicMock()
    callback.from_user.id = 1
    callback.message = MagicMock()
    callback.answer = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.sync.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr("bot.handlers.callback.sync.get_redis_client", lambda: fake_redis)

    await update_callback(callback, AsyncMock())
    await update_callback(callback, AsyncMock())

    delay.assert_called_once_with(1)
    assert callback.answer.await_count == 2


async def test_update_callback_for_unauthorized_user_shows_login(
    monkeypatch: pytest.MonkeyPatch,
    delay: MagicMock,
    ru_locale,
) -> None:
    monkeypatch.setattr("bot.handlers.callback.sync.Message", MagicMock)
    callback = MagicMock()
    callback.from_user.id = 1
    callback.message = MagicMock()
    callback.answer = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.sync.is_authorized", AsyncMock(return_value=False))
    show_menu = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.sync.show_main_menu", show_menu)

    await update_callback(callback, AsyncMock())

    delay.assert_not_called()
    show_menu.assert_awaited_once()
    assert "/start" in callback.answer.await_args.args[0]
