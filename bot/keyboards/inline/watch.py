"""Inline-клавиатура экрана режима ожидания (фаза 5)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup

#: Вход из главного меню (тот же `callback_data`, что у кнопки «Режим ожидания»).
CALLBACK_WATCH = "watch"
CALLBACK_EXTEND = "watch:extend"
CALLBACK_OFF = "watch:off"
CALLBACK_REFRESH = "watch:refresh"
CALLBACK_MENU = "watch:menu"


def get_watch_keyboard(*, active: bool) -> InlineKeyboardMarkup:
    """Кнопки экрана: у активного режима — продлить/выключить/обновить, у выключенного — включить."""
    builder = InlineKeyboardBuilder()
    if active:
        builder.button(text=_("watch.extend_btn"), callback_data=CALLBACK_EXTEND)
        builder.button(text=_("watch.off_btn"), callback_data=CALLBACK_OFF)
        builder.button(text=_("watch.refresh_btn"), callback_data=CALLBACK_REFRESH)
    else:
        builder.button(text=_("watch.enable_btn"), callback_data=CALLBACK_WATCH)
    builder.button(text=_("watch.menu_btn"), callback_data=CALLBACK_MENU)
    builder.adjust(2)
    return builder.as_markup()
