"""Экран `/settings`: переключения, время, меню и неавторизованный (задача 3.3)."""

from __future__ import annotations
import datetime as dt
from unittest.mock import ANY, AsyncMock, MagicMock

from bot.handlers.callback.settings import (
    settings_back_to_menu,
    settings_cycle_morning,
    settings_open,
    settings_toggle_night,
    settings_toggle_notifications,
)
from bot.handlers.message.settings import render_settings, settings_command
from bot.keyboards.inline.settings import (
    CALLBACK_MENU,
    CALLBACK_MORNING,
    CALLBACK_NIGHT,
    CALLBACK_NOTIFICATIONS,
)
from bot.services.users import (
    NotificationSettings,
    load_notification_settings,
    set_morning_notification,
    set_notification_enabled,
)


def _settings(
    *,
    enabled: bool = True,
    morning_enabled: bool = True,
    morning_time: dt.time = dt.time(8, 0),
) -> NotificationSettings:
    return NotificationSettings(
        enabled=enabled,
        morning_enabled=morning_enabled,
        morning_time=morning_time,
        language_code="ru",
    )


def _callback(monkeypatch) -> MagicMock:
    monkeypatch.setattr("bot.handlers.callback.settings.Message", MagicMock)
    callback = MagicMock()
    callback.from_user.id = 1
    callback.message = MagicMock()
    callback.message.message_id = 7
    callback.answer = AsyncMock()
    return callback


def test_render_settings_shows_state_and_time(ru_locale) -> None:
    text, keyboard = render_settings(_settings(morning_time=dt.time(9, 0)))

    assert "Настройки уведомлений" in text
    assert "Уведомления: вкл" in text
    assert "Копить ночью: вкл" in text
    assert "09:00" in text
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == [CALLBACK_NOTIFICATIONS, CALLBACK_NIGHT, CALLBACK_MORNING, CALLBACK_MENU]
    assert keyboard.inline_keyboard[-1][0].text == "🏠 Главное меню"


def test_render_settings_hides_morning_time_without_night_collection(ru_locale) -> None:
    text, keyboard = render_settings(_settings(morning_enabled=False, morning_time=dt.time(9, 0)))

    assert "Время утренней сводки" not in text
    assert "09:00" not in text
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == [CALLBACK_NOTIFICATIONS, CALLBACK_NIGHT, CALLBACK_MENU]


async def test_toggle_notifications_writes_db(monkeypatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    monkeypatch.setattr("bot.handlers.callback.settings.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "bot.handlers.callback.settings.load_notification_settings",
        AsyncMock(return_value=_settings(enabled=True)),
    )
    setter = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.settings.set_notification_enabled", setter)
    refresh = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.settings._refresh_screen", refresh)

    await settings_toggle_notifications(callback, AsyncMock())

    setter.assert_awaited_once_with(ANY, 1, enabled=False)
    refresh.assert_awaited_once()
    callback.answer.assert_awaited_once()


async def test_toggle_night_keeps_the_chosen_time(monkeypatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    monkeypatch.setattr("bot.handlers.callback.settings.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "bot.handlers.callback.settings.load_notification_settings",
        AsyncMock(return_value=_settings(morning_enabled=True, morning_time=dt.time(9, 0))),
    )
    setter = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.settings.set_morning_notification", setter)
    monkeypatch.setattr("bot.handlers.callback.settings._refresh_screen", AsyncMock())

    await settings_toggle_night(callback, AsyncMock())

    setter.assert_awaited_once_with(ANY, 1, enabled=False, morning_time=dt.time(9, 0))


async def test_morning_time_cycles_by_preset(monkeypatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    monkeypatch.setattr("bot.handlers.callback.settings.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "bot.handlers.callback.settings.load_notification_settings",
        AsyncMock(return_value=_settings(morning_enabled=False, morning_time=dt.time(10, 0))),
    )
    setter = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.settings.set_morning_notification", setter)
    monkeypatch.setattr("bot.handlers.callback.settings._refresh_screen", AsyncMock())

    await settings_cycle_morning(callback, AsyncMock())

    setter.assert_awaited_once_with(ANY, 1, enabled=False, morning_time=dt.time(7, 0))


async def test_open_settings_edits_the_same_message(monkeypatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    monkeypatch.setattr("bot.handlers.callback.settings.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "bot.handlers.callback.settings.load_notification_settings",
        AsyncMock(return_value=_settings()),
    )
    edit = AsyncMock(return_value=7)
    monkeypatch.setattr("bot.handlers.callback.settings.edit_bot_message", edit)

    await settings_open(callback, AsyncMock())

    edit.assert_awaited_once()
    assert edit.await_args.args[1] == 7
    assert "Настройки уведомлений" in edit.await_args.args[2]
    callback.answer.assert_awaited_once()


async def test_menu_button_returns_to_main_menu(monkeypatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    menu = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.settings.show_main_menu", menu)

    await settings_back_to_menu(callback, AsyncMock())

    menu.assert_awaited_once_with(callback.message, ANY, 1, 7)
    callback.answer.assert_awaited_once()


async def test_unauthorized_user_cannot_change_settings(monkeypatch, ru_locale) -> None:
    callback = _callback(monkeypatch)
    monkeypatch.setattr("bot.handlers.callback.settings.is_authorized", AsyncMock(return_value=False))
    setter = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.settings.set_notification_enabled", setter)
    menu = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.settings.show_main_menu", menu)

    await settings_toggle_notifications(callback, AsyncMock())

    setter.assert_not_awaited()
    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs["show_alert"] is True
    menu.assert_awaited_once()


async def test_settings_command_for_authorized_user(monkeypatch, ru_locale) -> None:
    message = MagicMock()
    message.from_user.id = 1
    message.answer = AsyncMock()
    monkeypatch.setattr("bot.handlers.message.settings.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "bot.handlers.message.settings.load_notification_settings",
        AsyncMock(return_value=_settings()),
    )

    await settings_command(message, AsyncMock())

    message.answer.assert_awaited_once()
    assert "Настройки уведомлений" in message.answer.await_args.args[0]


async def test_settings_command_for_unauthorized_user_asks_to_login(monkeypatch, ru_locale) -> None:
    message = MagicMock()
    message.from_user.id = 1
    message.answer = AsyncMock()
    monkeypatch.setattr("bot.handlers.message.settings.is_authorized", AsyncMock(return_value=False))
    monkeypatch.setattr("bot.handlers.message.settings.get_main_menu_keyboard", AsyncMock(return_value=None))
    monkeypatch.setattr("bot.handlers.message.settings.get_main_menu", AsyncMock(return_value="меню"))

    await settings_command(message, AsyncMock())

    assert "/start" in message.answer.await_args.args[0]


async def test_load_notification_settings_defaults_morning_time() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.first.return_value = (True, False, None, "ru")
    session.execute = AsyncMock(return_value=result)

    settings = await load_notification_settings(session, 1)

    assert settings == NotificationSettings(
        enabled=True,
        morning_enabled=False,
        morning_time=dt.time(8, 0),
        language_code="ru",
    )


async def test_load_notification_settings_for_unknown_user_returns_none() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.first.return_value = None
    session.execute = AsyncMock(return_value=result)

    assert await load_notification_settings(session, 1) is None


async def test_set_notification_enabled_commits_the_update() -> None:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    await set_notification_enabled(session, 1, enabled=False)

    statement = str(session.execute.await_args.args[0])
    assert "notification_enabled" in statement
    session.commit.assert_awaited_once()


async def test_set_morning_notification_commits_flag_and_time() -> None:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    await set_morning_notification(session, 1, enabled=True, morning_time=dt.time(7, 0))

    statement = str(session.execute.await_args.args[0])
    assert "morning_notification_enabled" in statement
    assert "morning_notification_time" in statement
    session.commit.assert_awaited_once()
