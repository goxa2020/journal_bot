"""Экран `/settings`: уведомления, ночное накопление и время утра (задача 3.3).

Экран читает и пишет только БД: сети нет. Вся политика уведомлений живёт в
`bot/services/notifications.py`, здесь — тексты, кнопки и изменения настроек.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.utils.i18n import gettext as _

from bot.keyboards.inline.menu import get_main_menu_keyboard
from bot.keyboards.inline.settings import format_morning_time, get_settings_keyboard, state_label
from bot.services.users import is_authorized, load_notification_settings
from bot.utils.main_menu import get_main_menu

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup, Message
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.services.users import NotificationSettings

router = Router(name="settings")


def render_settings(settings: NotificationSettings) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура экрана настроек из текущих значений БД.

    Время утренней сводки показывается только при включённом накоплении: без него
    ночных сообщений нет, и настройка была бы недействующей.
    """
    lines = [
        _("settings.title"),
        "",
        _("settings.notifications_line").format(state=state_label(settings.enabled)),
        _("settings.night_line").format(state=state_label(settings.morning_enabled)),
    ]
    if settings.morning_enabled:
        lines.append(_("settings.morning_line").format(time=format_morning_time(settings)))
    lines.extend(("", _("settings.hint")))
    return "\n".join(lines), get_settings_keyboard(settings)


async def load_settings_screen(session: AsyncSession, user_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    """Экран из БД; `None` — пользователя нет или он не авторизован."""
    settings = await load_notification_settings(session, user_id)
    if settings is None:
        return None
    return render_settings(settings)


async def send_login_required(message: Message, session: AsyncSession, user_id: int) -> None:
    """Приглашение войти вместо экрана настроек."""
    kb = await get_main_menu_keyboard(session, user_id)
    text = _("settings.login_required") + "\n\n" + await get_main_menu(session, user_id)
    await message.answer(text, reply_markup=kb)


@router.message(Command("settings"))
async def settings_command(message: Message, session: AsyncSession) -> None:
    """Показать настройки уведомлений; неавторизованного — позвать войти."""
    if not message.from_user:
        return
    user_id = message.from_user.id

    if not await is_authorized(session, user_id):
        await send_login_required(message, session, user_id)
        return

    screen = await load_settings_screen(session, user_id)
    if screen is None:
        await send_login_required(message, session, user_id)
        return

    text, kb = screen
    await message.answer(text, reply_markup=kb)
