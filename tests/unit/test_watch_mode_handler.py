"""Экран «Режим ожидания»: тексты, нажатия и отказ без входа (задача 5.1)."""

from __future__ import annotations
import datetime as dt
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.callback.stubs import STUB_CALLBACKS
from bot.handlers.callback.watch import (
    render_watch_screen,
    watch_extend,
    watch_menu,
    watch_off,
    watch_open,
    watch_refresh,
)
from bot.keyboards.inline.watch import (
    CALLBACK_EXTEND,
    CALLBACK_MENU,
    CALLBACK_OFF,
    CALLBACK_REFRESH,
    CALLBACK_WATCH,
)
from bot.services.watch import REASON_NOT_AUTHENTICATED, WatchOutcome, WatchState

#: Наивное время, как в `users.watch_mode_expires_at` (TIMESTAMP без tz, московское).
NOW = dt.datetime(2026, 11, 27, 12, 0, 0)  # noqa: DTZ001


class FakeService:
    def __init__(self, state: WatchState, outcome: WatchOutcome | None = None) -> None:
        self.state = state
        self.outcome = outcome
        self.enabled = 0
        self.disabled = 0

    async def get_state(self, _user_id: int) -> WatchState:
        return self.state

    async def enable(self, _user_id: int) -> WatchOutcome:
        self.enabled += 1
        return self.outcome or WatchOutcome(state=self.state, changed=True)

    async def disable(self, _user_id: int) -> WatchOutcome:
        self.disabled += 1
        return WatchOutcome(state=WatchState(active=False), changed=True)


def _active() -> WatchState:
    return WatchState(active=True, expires_at=NOW + dt.timedelta(minutes=30), minutes_left=30)


def _callback(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr("bot.handlers.callback.watch.Message", MagicMock)
    callback = MagicMock()
    callback.from_user.id = 1
    callback.message = MagicMock()
    callback.message.message_id = 7
    callback.answer = AsyncMock()
    return callback


def _install(monkeypatch: pytest.MonkeyPatch, service: FakeService) -> tuple[AsyncMock, AsyncMock]:
    edit = AsyncMock(return_value=7)
    menu = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.watch.edit_bot_message", edit)
    monkeypatch.setattr("bot.handlers.callback.watch.show_main_menu", menu)
    monkeypatch.setattr("bot.handlers.callback.watch._service", lambda _session: service)
    return edit, menu


def _text(edit: AsyncMock) -> str:
    return str(edit.call_args.args[2])


def test_render_off_screen(ru_locale) -> None:
    text, keyboard = render_watch_screen(WatchState(active=False))

    assert "Режим ожидания выключен" in text
    assert "каждые 5 мин" in text
    assert "в течение 30 мин" in text
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == [CALLBACK_WATCH, CALLBACK_MENU]


def test_render_active_screen(ru_locale) -> None:
    text, keyboard = render_watch_screen(_active())

    assert "Режим ожидания включён" in text
    assert "Осталось: 30 мин" in text
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == [CALLBACK_EXTEND, CALLBACK_OFF, CALLBACK_REFRESH, CALLBACK_MENU]


def test_watch_is_not_a_stub_anymore() -> None:
    assert "watch" not in STUB_CALLBACKS


async def test_open_enables_mode_and_shows_screen(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    service = FakeService(WatchState(active=False), WatchOutcome(state=_active(), changed=True))
    edit, _menu = _install(monkeypatch, service)

    await watch_open(callback, MagicMock())

    assert service.enabled == 1
    assert "Режим ожидания включён" in _text(edit)
    callback.answer.assert_awaited_once_with("Режим ожидания включён")


async def test_open_does_not_enable_twice(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    service = FakeService(_active())
    edit, _menu = _install(monkeypatch, service)

    await watch_open(callback, MagicMock())

    assert service.enabled == 0
    assert "Осталось: 30 мин" in _text(edit)
    callback.answer.assert_awaited_once()


async def test_open_without_login_returns_to_menu(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    service = FakeService(
        WatchState(active=False),
        WatchOutcome(state=WatchState(active=False), changed=False, reason=REASON_NOT_AUTHENTICATED),
    )
    edit, menu = _install(monkeypatch, service)

    await watch_open(callback, MagicMock())

    menu.assert_awaited_once()
    edit.assert_not_called()
    callback.answer.assert_awaited_once()
    assert "Сначала войдите" in callback.answer.call_args.args[0]


async def test_extend_refreshes_screen(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    service = FakeService(_active())
    edit, _menu = _install(monkeypatch, service)

    await watch_extend(callback, MagicMock())

    assert service.enabled == 1
    assert "Осталось: 30 мин" in _text(edit)
    callback.answer.assert_awaited_once_with("Режим ожидания включён")


async def test_off_disables_and_shows_off_screen(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    service = FakeService(WatchState(active=False))
    edit, _menu = _install(monkeypatch, service)

    await watch_off(callback, MagicMock())

    assert service.disabled == 1
    assert "Режим ожидания выключен" in _text(edit)
    callback.answer.assert_awaited_once_with("Режим ожидания выключен")


async def test_refresh_redraws_without_changes(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    service = FakeService(_active())
    edit, _menu = _install(monkeypatch, service)

    await watch_refresh(callback, MagicMock())

    assert service.enabled == 0
    assert service.disabled == 0
    assert "Осталось: 30 мин" in _text(edit)
    callback.answer.assert_awaited_once()


async def test_menu_returns_to_main_menu(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    service: Any = FakeService(WatchState(active=False))
    _edit, menu = _install(monkeypatch, service)

    await watch_menu(callback, MagicMock())

    menu.assert_awaited_once()
    callback.answer.assert_awaited_once()


async def test_answer_is_called_when_rendering_fails(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    """Спиннер на кнопке не должен остаться, даже если сервис упал."""
    callback = _callback(monkeypatch)
    service = FakeService(WatchState(active=False))
    _install(monkeypatch, service)

    async def boom(_user_id: int) -> WatchState:
        message = "БД недоступна"
        raise RuntimeError(message)

    monkeypatch.setattr(service, "get_state", boom)

    with pytest.raises(RuntimeError):
        await watch_refresh(callback, MagicMock())

    callback.answer.assert_awaited_once()
