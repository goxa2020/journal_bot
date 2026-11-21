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

#: Ширина строк таблицы (задача 2.9). Telegram считает `<pre>` посимвольно.
TABLE_WIDTH = 50
DATE_WIDTH = 12
KIND_WIDTH = 14
VALUE_WIDTH = 20
EMPTY_CELL = "—"
ELLIPSIS = "…"


#: Сколько журналов с ошибками перечислять в сводке.
MAX_ERROR_JOURNALS = 5


class Translator(Protocol):
    """Функция перевода: `_()` в обработчиках, gettext-каталог в воркере."""

    def __call__(self, message: str) -> str: ...


def format_date(value: date) -> str:
    """Дата в формате ДД.ММ.ГГГГ."""
    return value.strftime(DATE_FORMAT)


def format_last_grade(value: str, journal_name: str, grade_date: date) -> str:
    """Строка «последняя оценка» для главного меню."""
    return _("last_grade").format(value, journal_name, format_date(grade_date))


def _truncate(value: str, width: int) -> str:
    text = value.replace("\n", " ").strip()
    if width <= 0:
        return ""
    if len(text) > width:
        text = text[: width - 1] + ELLIPSIS
    return text


def _fit(value: str, width: int) -> str:
    """Обрезать строку до ширины колонки и дополнить пробелами."""
    return _truncate(value, width).ljust(width)


def _journal_type_suffix(journal_type: str) -> str:
    """Пометка вида занятия: лекция и практика часто называются одинаково."""
    raw = journal_type.strip().lower()
    if raw.startswith("лек") or raw == "л":
        return _("grades.type_lecture")
    if raw.startswith("пр") or raw == "п":
        return _("grades.type_practice")
    if raw.startswith("лаб"):
        return _("grades.type_lab")
    return ""


def journal_display_name(name: str, journal_type: str) -> str:
    """Название журнала с пометкой «Л»/«П»/«Лаб» в конце."""
    suffix = _journal_type_suffix(journal_type)
    return f"{name} {suffix}" if suffix else name


def _table_header() -> str:
    return "  ".join(
        (
            _fit(_("grades.col_date"), DATE_WIDTH),
            _fit(_("grades.col_kind"), KIND_WIDTH),
            _fit(_("grades.col_value"), VALUE_WIDTH),
        ),
    )


def _grade_cells(grade: object) -> tuple[str, str]:
    """(вид, значение): оценка и посещаемость не могут быть одновременно."""
    value = str(getattr(grade, "value", "") or "")
    is_mark = bool(getattr(grade, "is_mark", False))
    is_pass = bool(getattr(grade, "is_pass", False))
    if is_mark:
        return _("grades.kind_mark"), value or EMPTY_CELL
    if is_pass:
        return _("grades.kind_pass"), value or EMPTY_CELL
    return EMPTY_CELL, value or EMPTY_CELL


def format_grades_table(title: str, grades: Sequence[object]) -> str:
    """Таблица одного журнала: дата, вид занятия и значение, ширина — 50 символов."""
    rows = [_table_header(), "-" * TABLE_WIDTH]
    for grade in grades:
        kind, value = _grade_cells(grade)
        grade_date = getattr(grade, "date", None)
        rows.append(
            "  ".join(
                (
                    _fit(format_date(grade_date) if grade_date else EMPTY_CELL, DATE_WIDTH),
                    _fit(kind, KIND_WIDTH),
                    _fit(value, VALUE_WIDTH),
                ),
            ),
        )

    table = "\n".join(rows)
    return f"<b>{html.escape(title)}</b>\n<pre>{html.escape(table)}</pre>"


def format_average(average: float | None) -> str:
    """Средний балл по журналу; `—`, если числовых оценок ещё нет."""
    if average is None:
        return _("grades.average_none")
    return _("grades.average").format(f"{average:.2f}")


def format_journals_overview(journals: Sequence[JournalSummary]) -> str:
    """Список журналов: название с пометкой вида и средний балл, строки до 50 символов."""
    lines: list[str] = []
    for journal in journals:
        name = journal_display_name(journal.name, journal.type)
        average = f"{journal.average:.2f}" if journal.average is not None else EMPTY_CELL
        line = _("grades.journal_line").format(name, average)
        if len(line) > TABLE_WIDTH:
            # Обрезаем само название, а пометку вида («Л»/«П») сохраняем.
            excess = len(line) - TABLE_WIDTH
            base = _truncate(journal.name, max(1, len(journal.name) - excess))
            name = journal_display_name(base, journal.type)
            line = _("grades.journal_line").format(name, average)
        lines.append(line)
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
