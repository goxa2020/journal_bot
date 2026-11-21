"""Inline-клавиатуры экрана оценок (задача 2.8)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.utils.formatters import journal_display_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InlineKeyboardMarkup

    from bot.services.grades import JournalSummary

#: Telegram ограничивает длину текста кнопки; длинные названия обрезаем.
BUTTON_NAME_LIMIT = 32


def _journal_button_text(journal: JournalSummary) -> str:
    full_name = journal_display_name(journal.name, journal.type)
    name = full_name if len(full_name) <= BUTTON_NAME_LIMIT else full_name[: BUTTON_NAME_LIMIT - 1] + "…"
    if journal.average is None:
        return name
    return f"{name} · {journal.average:.2f}"


def get_journals_keyboard(journals: Sequence[JournalSummary]) -> InlineKeyboardMarkup:
    """Список журналов: по кнопке на журнал, ниже «Обновить» и «Главное меню»."""
    builder = InlineKeyboardBuilder()
    for journal in journals:
        builder.button(text=_journal_button_text(journal), callback_data=f"grades:j:{journal.id}")
    builder.button(text=_("grades.update_btn"), callback_data="update")
    builder.button(text=_("grades.back_btn"), callback_data="grades:menu")
    builder.adjust(1)
    return builder.as_markup()


def get_grades_keyboard() -> InlineKeyboardMarkup:
    """Экран одного журнала: «Главное меню» и «К списку» поменяны местами."""
    builder = InlineKeyboardBuilder()
    builder.button(text=_("grades.back_btn"), callback_data="grades:menu")
    builder.button(text=_("grades.update_btn"), callback_data="update")
    builder.button(text=_("grades.to_list_btn"), callback_data="grades:list")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_grades_empty_keyboard() -> InlineKeyboardMarkup:
    """Пустое состояние: предложить обновить или вернуться."""
    builder = InlineKeyboardBuilder()
    builder.button(text=_("grades.update_btn"), callback_data="update")
    builder.button(text=_("grades.back_btn"), callback_data="grades:menu")
    builder.button(text=_("grades.to_list_btn"), callback_data="grades:list")
    builder.adjust(2, 1)
    return builder.as_markup()
