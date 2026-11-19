from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from pydantic import ValidationError

from bot.keyboards.inline.auth import get_cancel_inline_keyboard
from bot.services.auth import edit_bot_message


def test_cancel_keyboard_is_inline(ru_locale) -> None:
    keyboard = get_cancel_inline_keyboard()

    assert isinstance(keyboard, InlineKeyboardMarkup)
    assert keyboard.inline_keyboard[0][0].callback_data == "auth_cancel"


def test_edit_message_text_accepts_inline_keyboard(ru_locale) -> None:
    # Регрессия: reply-клавиатура в edit_message_text давала ValidationError
    # и ломала вход в edu-tpi (fix(auth): repair edu-tpi login flow).
    method = EditMessageText(
        chat_id=1,
        message_id=2,
        text="Введите пароль",
        reply_markup=get_cancel_inline_keyboard(),
    )

    assert method.reply_markup is not None
    assert isinstance(method.reply_markup, InlineKeyboardMarkup)


def test_edit_message_text_rejects_reply_keyboard() -> None:
    reply_keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]])

    with pytest.raises(ValidationError):
        EditMessageText(chat_id=1, message_id=2, text="x", reply_markup=reply_keyboard)


async def test_edit_bot_message_returns_same_id_when_not_modified(ru_locale) -> None:
    message = MagicMock()
    message.chat.id = 100
    message.bot = MagicMock()
    message.bot.edit_message_text = AsyncMock(
        side_effect=TelegramBadRequest(None, "Bad Request: message is not modified: specified new message content"),
    )
    message.answer = AsyncMock()

    message_id = await edit_bot_message(message, 77, "тот же текст", get_cancel_inline_keyboard())

    assert message_id == 77
    message.answer.assert_not_awaited()


async def test_edit_bot_message_sends_new_message_on_other_error() -> None:
    message = MagicMock()
    message.chat.id = 100
    message.bot = MagicMock()
    message.bot.edit_message_text = AsyncMock(
        side_effect=TelegramBadRequest(None, "Bad Request: message to edit not found"),
    )
    message.answer = AsyncMock(return_value=MagicMock(message_id=99))

    message_id = await edit_bot_message(message, 77, "текст")

    assert message_id == 99
    message.answer.assert_awaited_once()
