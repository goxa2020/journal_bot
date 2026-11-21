"""Callback-обработчики экрана `/settings` (задача 3.3).

Один экран — одно сообщение: открытие, переключения и возврат в меню правят его
`edit_message_text`, новых сообщений не появляется.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _

from bot.handlers.message.auth import show_main_menu
from bot.handlers.message.settings import load_settings_screen, render_settings
from bot.keyboards.inline.settings import CALLBACK_MENU, CALLBACK_MORNING, CALLBACK_NIGHT, CALLBACK_NOTIFICATIONS
from bot.services.auth import edit_bot_message
from bot.services.notifications import next_morning_preset
from bot.services.users import (
    is_authorized,
    load_notification_settings,
    set_morning_notification,
    set_notification_enabled,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.services.users import NotificationSettings

router = Router(name="settings_callback")


async def _authorized_settings(
    callback: CallbackQuery,
    session: AsyncSession,
) -> NotificationSettings | None:
    """Проверить авторизацию и вернуть настройки; иначе — алерт и меню."""
    user_id = callback.from_user.id
    if not await is_authorized(session, user_id):
        await callback.answer(_("settings.login_required"), show_alert=True)
        if isinstance(callback.message, Message):
            await show_main_menu(callback.message, session, user_id, callback.message.message_id)
        return None

    settings = await load_notification_settings(session, user_id)
    if settings is None:
        await callback.answer(_("settings.login_required"), show_alert=True)
        return None
    return settings


async def _refresh_screen(callback: CallbackQuery, session: AsyncSession) -> None:
    """Перерисовать экран после изменения настроек."""
    if not isinstance(callback.message, Message):
        return
    screen = await load_settings_screen(session, callback.from_user.id)
    if screen is None:
        return
    text, kb = screen
    await edit_bot_message(callback.message, callback.message.message_id, text, kb)


@router.callback_query(F.data == "settings")
async def settings_open(callback: CallbackQuery, session: AsyncSession) -> None:
    """Кнопка «Настройки» в главном меню."""
    settings = await _authorized_settings(callback, session)
    if settings is None:
        return

    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    text, kb = render_settings(settings)
    await edit_bot_message(callback.message, callback.message.message_id, text, kb)
    await callback.answer()


@router.callback_query(F.data == CALLBACK_NOTIFICATIONS)
async def settings_toggle_notifications(callback: CallbackQuery, session: AsyncSession) -> None:
    """Включить/выключить уведомления."""
    settings = await _authorized_settings(callback, session)
    if settings is None:
        return

    await set_notification_enabled(session, callback.from_user.id, enabled=not settings.enabled)
    await _refresh_screen(callback, session)
    await callback.answer()


@router.callback_query(F.data == CALLBACK_NIGHT)
async def settings_toggle_night(callback: CallbackQuery, session: AsyncSession) -> None:
    """Включить/выключить накопление ночью, сохранив выбранное время."""
    settings = await _authorized_settings(callback, session)
    if settings is None:
        return

    await set_morning_notification(
        session,
        callback.from_user.id,
        enabled=not settings.morning_enabled,
        morning_time=settings.morning_time,
    )
    await _refresh_screen(callback, session)
    await callback.answer()


@router.callback_query(F.data == CALLBACK_MORNING)
async def settings_cycle_morning(callback: CallbackQuery, session: AsyncSession) -> None:
    """Следующий пресет времени утра по кругу: 07:00 → 08:00 → 09:00 → 10:00."""
    settings = await _authorized_settings(callback, session)
    if settings is None:
        return

    await set_morning_notification(
        session,
        callback.from_user.id,
        enabled=settings.morning_enabled,
        morning_time=next_morning_preset(settings.morning_time),
    )
    await _refresh_screen(callback, session)
    await callback.answer()


@router.callback_query(F.data == CALLBACK_MENU)
async def settings_back_to_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """«Главное меню»: вернуть меню в то же сообщение."""
    if isinstance(callback.message, Message):
        await show_main_menu(callback.message, session, callback.from_user.id, callback.message.message_id)
    await callback.answer()
