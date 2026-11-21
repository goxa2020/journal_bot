"""Callback-обработчики экрана оценок (задача 2.8).

Всё живёт в одном сообщении: список журналов, таблица и возврат в меню правят
`edit_message_text`, а не отправляют новые сообщения.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _

from bot.handlers.message.auth import show_main_menu
from bot.handlers.message.grades import render_journal, render_journals
from bot.services.auth import edit_bot_message
from bot.services.users import is_authorized

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="grades_callback")

JOURNAL_PREFIX = "grades:j:"


@router.callback_query(F.data == "grades")
async def grades_open(callback: CallbackQuery, session: AsyncSession) -> None:
    """Кнопка «Оценки» в главном меню."""
    if not isinstance(callback.message, Message):
        return
    user_id = callback.from_user.id
    await callback.answer()

    if not await is_authorized(session, user_id):
        await show_main_menu(callback.message, session, user_id, callback.message.message_id)
        return

    text, kb = await render_journals(session, user_id)
    await edit_bot_message(callback.message, callback.message.message_id, text, kb)


@router.callback_query(F.data == "grades:list")
async def grades_back_to_list(callback: CallbackQuery, session: AsyncSession) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    text, kb = await render_journals(session, callback.from_user.id)
    await edit_bot_message(callback.message, callback.message.message_id, text, kb)


@router.callback_query(F.data == "grades:menu")
async def grades_back_to_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    if not isinstance(callback.message, Message):
        return
    await show_main_menu(callback.message, session, callback.from_user.id, callback.message.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith(JOURNAL_PREFIX))
async def grades_show_journal(callback: CallbackQuery, session: AsyncSession) -> None:
    """Таблица оценок выбранного журнала."""
    if not isinstance(callback.message, Message):
        return
    if not isinstance(callback.data, str):
        return

    user_id = callback.from_user.id
    raw_id = callback.data.removeprefix(JOURNAL_PREFIX)
    try:
        journal_id = int(raw_id)
    except ValueError:
        await callback.answer(_("grades.not_found"), show_alert=True)
        return

    rendered = await render_journal(session, user_id, journal_id)
    if rendered is None:
        # Чужой или уже удалённый журнал: понятная ошибка вместо трейсбека.
        await callback.answer(_("grades.not_found"), show_alert=True)
        text, kb = await render_journals(session, user_id)
        await edit_bot_message(callback.message, callback.message.message_id, text, kb)
        return

    await callback.answer()
    text, kb = rendered
    await edit_bot_message(callback.message, callback.message.message_id, text, kb)
