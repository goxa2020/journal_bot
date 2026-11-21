"""Форматирование пользовательских текстов.

Здесь только преобразование данных в строку: сервисы не знают про текст,
хендлеры не собирают строки вручную. Все подписи — через gettext.
"""

from __future__ import annotations
import html
from typing import TYPE_CHECKING, Protocol

from aiogram.utils.i18n import gettext as _

from bot.utils.misc import n_

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    from bot.services.grade_sync import SyncSummary
    from bot.services.grades import JournalSummary

DATE_FORMAT = "%d.%m.%Y"

#: Ширина таблицы оценок в символах (задача 2.9). Telegram считает `<pre>` посимвольно.
TABLE_WIDTH = 86
SUBJECT_WIDTH = 42
DATE_WIDTH = 10
PAIR_WIDTH = 6
GRADE_WIDTH = 8
VISIT_WIDTH = 12
EMPTY_CELL = "—"
ELLIPSIS = "…"


#: Сколько журналов с ошибками перечислять в сводке.
MAX_ERROR_JOURNALS = 5

#: Ширина названия журнала в списке `/grades` (не таблица: строки свободнее).
OVERVIEW_NAME_WIDTH = 40


class Translator(Protocol):
    """Функция перевода: `_()` в обработчиках, gettext-каталог в воркере."""

    def __call__(self, message: str) -> str: ...


def format_date(value: date) -> str:
    """Дата в формате ДД.ММ.ГГГГ."""
    return value.strftime(DATE_FORMAT)


def format_last_grade(value: str, journal_name: str, grade_date: date) -> str:
    """Строка «последняя оценка» для главного меню."""
    return _("last_grade").format(value, journal_name, format_date(grade_date))


def _fit(value: str, width: int) -> str:
    """Обрезать строку до ширины колонки и дополнить пробелами.

    Обрезка идёт по символам, как их считает Telegram в `<pre>`; длинное название
    предмета не должно рвать таблицу (задача 2.9).
    """
    text = value.replace("\n", " ").strip()
    if len(text) > width:
        text = text[: width - 1] + ELLIPSIS
    return text.ljust(width)


def _table_header() -> str:
    return "  ".join(
        (
            _fit(_("grades.col_subject"), SUBJECT_WIDTH),
            _fit(_("grades.col_date"), DATE_WIDTH),
            _fit(_("grades.col_pair"), PAIR_WIDTH),
            _fit(_("grades.col_grade"), GRADE_WIDTH),
            _fit(_("grades.col_visit"), VISIT_WIDTH),
        ),
    )


def _grade_cells(grade: object) -> tuple[str, str]:
    """(оценка, посещаемость): числовая оценка и буквенный пропуск не смешиваются."""
    value = str(getattr(grade, "value", "") or "")
    is_mark = bool(getattr(grade, "is_mark", False))
    is_pass = bool(getattr(grade, "is_pass", False))
    if is_mark:
        return value or EMPTY_CELL, EMPTY_CELL
    if is_pass:
        return EMPTY_CELL, value or EMPTY_CELL
    return (value or EMPTY_CELL), EMPTY_CELL


def format_grades_table(title: str, grades: Sequence[object]) -> str:
    """Таблица оценок одного журнала: заголовок, `<pre>` шириной 86 и легенда."""
    rows = [_table_header(), "-" * TABLE_WIDTH]
    for grade in grades:
        grade_cell, visit_cell = _grade_cells(grade)
        grade_date = getattr(grade, "date", None)
        hour_number = getattr(grade, "hour_number", "")
        rows.append(
            "  ".join(
                (
                    _fit(title, SUBJECT_WIDTH),
                    _fit(format_date(grade_date) if grade_date else EMPTY_CELL, DATE_WIDTH),
                    _fit(str(hour_number), PAIR_WIDTH),
                    _fit(grade_cell, GRADE_WIDTH),
                    _fit(visit_cell, VISIT_WIDTH),
                ),
            ),
        )

    table = "\n".join(rows)
    return f"<b>{html.escape(title)}</b>\n<pre>{html.escape(table)}</pre>"


def format_grades_legend() -> str:
    """Легенда обозначений под таблицей: Н, У, Б, О."""
    return _("grades.legend")


def format_average(average: float | None) -> str:
    """Средний балл по журналу; `—`, если числовых оценок ещё нет."""
    if average is None:
        return _("grades.average_none")
    return _("grades.average").format(f"{average:.2f}")


def format_journals_overview(journals: Sequence[JournalSummary]) -> str:
    """Список журналов для экрана `/grades`: название, средний балл, число оценок."""
    lines: list[str] = []
    for journal in journals:
        name = (
            journal.name
            if len(journal.name) <= OVERVIEW_NAME_WIDTH
            else journal.name[: OVERVIEW_NAME_WIDTH - 1] + ELLIPSIS
        )
        average = f"{journal.average:.2f}" if journal.average is not None else EMPTY_CELL
        lines.append(_("grades.journal_line").format(name, average, journal.grades_count))
    return "\n".join(lines)


def format_sync_summary(summary: SyncSummary, translate: Translator | None = None) -> str:
    """Текст сводки синхронизации для пользователя (и для лога — без ПДн)."""
    t: Callable[[str], str] = translate or _
    if summary.new_grades or summary.updated_grades:
        head = t(n_("sync.summary")).format(new=summary.new_grades, updated=summary.updated_grades)
    else:
        head = t(n_("sync.no_changes"))

    failed = [journal for journal in summary.journals if journal.error is not None]
    if not failed:
        return head

    lines = [head, t(n_("sync.partial_errors")).format(count=len(failed))]
    lines.extend(t(n_("sync.journal_error")).format(name=journal.name) for journal in failed[:MAX_ERROR_JOURNALS])
    if len(failed) > MAX_ERROR_JOURNALS:
        lines.append(t(n_("sync.more_errors")).format(count=len(failed) - MAX_ERROR_JOURNALS))
    return "\n".join(lines)
