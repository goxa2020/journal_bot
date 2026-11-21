"""Inline-клавиатура экрана `/settings` (задача 3.3)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup

    from bot.services.users import NotificationSettings

CALLBACK_NOTIFICATIONS = "settings:notify"
CALLBACK_NIGHT = "settings:night"
CALLBACK_MORNING = "settings:time"
CALLBACK_MENU = "settings:menu"


def format_morning_time(settings: NotificationSettings) -> str:
    """Время утра в виде `HH:MM`; `None` в БД — значение по умолчанию."""
    return settings.morning_time.strftime("%H:%M")


def state_label(enabled: bool) -> str:
    """«вкл»/«выкл» для кнопок и текста экрана."""
    return _("settings.state_on") if enabled else _("settings.state_off")


def get_settings_keyboard(settings: NotificationSettings) -> InlineKeyboardMarkup:
    """Кнопки экрана: два флага, время утра (если накопление включено) и меню.

    Время утра имеет смысл только при включённом накоплении: без него ночных
    сообщений нет, и настройка убирается с экрана, чтобы не путать.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("settings.notifications_btn").format(state=state_label(settings.enabled)),
        callback_data=CALLBACK_NOTIFICATIONS,
    )
    builder.button(
        text=_("settings.night_btn").format(state=state_label(settings.morning_enabled)),
        callback_data=CALLBACK_NIGHT,
    )
    if settings.morning_enabled:
        builder.button(
            text=_("settings.morning_btn").format(time=format_morning_time(settings)),
            callback_data=CALLBACK_MORNING,
        )
    builder.button(text=_("settings.menu_btn"), callback_data=CALLBACK_MENU)
    builder.adjust(1)
    return builder.as_markup()
