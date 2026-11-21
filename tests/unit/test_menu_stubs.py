from __future__ import annotations
from unittest.mock import AsyncMock

from bot.handlers.callback.stubs import STUB_CALLBACKS, stub_handler
from bot.keyboards.inline.menu import get_main_menu_keyboard

IMPLEMENTED_CALLBACKS = {"grades", "update", "settings"}


async def test_authorized_menu_buttons_are_implemented_or_stubbed(monkeypatch, ru_locale) -> None:
    monkeypatch.setattr("bot.keyboards.inline.menu.is_authorized", AsyncMock(return_value=True))

    keyboard = await get_main_menu_keyboard(AsyncMock(), 1)
    callbacks = {button.callback_data for row in keyboard.inline_keyboard for button in row}

    assert callbacks
    assert callbacks <= set(STUB_CALLBACKS) | IMPLEMENTED_CALLBACKS
    # Фаза 2 закрыла «Оценки» и «Обновить», фаза 3 — «Настройки».
    assert callbacks >= IMPLEMENTED_CALLBACKS
    assert not (IMPLEMENTED_CALLBACKS & set(STUB_CALLBACKS))


async def test_stub_handler_answers_in_development(ru_locale) -> None:
    callback = AsyncMock()

    await stub_handler(callback)

    callback.answer.assert_awaited_once_with("🚧 В разработке")
