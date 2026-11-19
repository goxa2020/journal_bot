"""Форматирование пользовательских текстов.

Здесь только преобразование данных в строку: сервисы не знают про текст,
хендлеры не собирают строки вручную. Все подписи — через gettext.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram.utils.i18n import gettext as _

if TYPE_CHECKING:
    from datetime import date

DATE_FORMAT = "%d.%m.%Y"


def format_date(value: date) -> str:
    """Дата в формате ДД.ММ.ГГГГ."""
    return value.strftime(DATE_FORMAT)


def format_last_grade(value: str, journal_name: str, grade_date: date) -> str:
    """Строка «последняя оценка» для главного меню."""
    return _("last_grade").format(value, journal_name, format_date(grade_date))
