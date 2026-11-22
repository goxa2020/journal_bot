"""Форматирование пользовательских текстов.

Здесь только преобразование данных в строку: сервисы не знают про текст,
хендлеры не собирают строки вручную. Все подписи — через gettext.
"""

from __future__ import annotations
import html
from typing import TYPE_CHECKING, Protocol

from aiogram.utils.i18n import gettext as _
from wcwidth import wcswidth

from bot.utils.misc import n_

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    from bot.services.grade_sync import NewGradeNotice, SyncSummary
    from bot.services.grades import JournalSummary

DATE_FORMAT = "%d.%m.%Y"

#: Максимальная ширина строки списка и таблицы (Telegram считает `<pre>` посимвольно).
TABLE_WIDTH = 50
DATE_WIDTH = 12
VALUE_WIDTH = 20
#: Таблица конкретного журнала: дата + один столбец «оценка/посещение».
GRADES_TABLE_WIDTH = DATE_WIDTH + 2 + VALUE_WIDTH
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


def display_width(value: str) -> int:
    """Ширина строки в моноширинных ячейках, а не в code points.

    Telegram считает `<pre>` посимвольно в моноширинном шрифте: эмодзи занимают две
    ячейки, CJK — две, комбинирующие знаки — ноль. `len()` на таких строках сдвигает
    колонки, поэтому ширина считается через `wcwidth`. Для управляющих символов
    `wcswidth` возвращает `-1` — тогда откатываемся на длину строки.
    """
    width = wcswidth(value)
    return len(value) if width < 0 else width


def _truncate(value: str, width: int) -> str:
    text = value.replace("\n", " ").strip()
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    if width == 1:
        return ELLIPSIS
    # Оставляем место под многоточие и режем по ячейкам, а не по символам.
    limit = width - display_width(ELLIPSIS)
    taken = 0
    cut = 0
    for index, char in enumerate(text):
        char_width = max(display_width(char), 0)
        if taken + char_width > limit:
            break
        taken += char_width
        cut = index + 1
    return text[:cut] + ELLIPSIS


def _fit(value: str, width: int) -> str:
    """Обрезать строку до ширины колонки и дополнить пробелами по ячейкам."""
    text = _truncate(value, width)
    padding = width - display_width(text)
    return text + " " * max(padding, 0)


def _journal_type_suffix(journal_type: str, translate: Translator | None = None) -> str:
    """Пометка вида занятия: лекция и практика часто называются одинаково."""
    t: Callable[[str], str] = translate or _
    raw = journal_type.strip().lower()
    if raw.startswith("лек") or raw == "л":
        return t(n_("grades.type_lecture"))
    if raw.startswith("пр") or raw == "п":
        return t(n_("grades.type_practice"))
    if raw.startswith("лаб"):
        return t(n_("grades.type_lab"))
    return ""


def journal_display_name(name: str, journal_type: str, translate: Translator | None = None) -> str:
    """Название журнала с пометкой «Л»/«П»/«Лаб» в конце.

    `translate` нужен воркеру: там нет aiogram-контекста i18n, и `_()` не работает.
    """
    suffix = _journal_type_suffix(journal_type, translate)
    return f"{name} {suffix}" if suffix else name


def _table_header() -> str:
    return "  ".join(
        (
            _fit(_("grades.col_date"), DATE_WIDTH),
            _fit(_("grades.col_value"), VALUE_WIDTH),
        ),
    )


def _grade_value(grade: object) -> str:
    """Значение: числовая оценка или буквенный пропуск в одном столбце."""
    value = str(getattr(grade, "value", "") or "")
    return value or EMPTY_CELL


def format_grades_table(title: str, grades: Sequence[object]) -> str:
    """Таблица одного журнала: дата и одно значение, не шире 50 символов."""
    rows = [_table_header(), "-" * GRADES_TABLE_WIDTH]
    for grade in grades:
        grade_date = getattr(grade, "date", None)
        rows.append(
            "  ".join(
                (
                    _fit(format_date(grade_date) if grade_date else EMPTY_CELL, DATE_WIDTH),
                    _fit(_grade_value(grade), VALUE_WIDTH),
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


def _overview_line(name: str, average: str | None) -> str:
    """Строка списка: без числовых оценок — только название, без «— —»."""
    if average is None:
        return _("grades.journal_line_no_average").format(name)
    return _("grades.journal_line").format(name, average)


def format_journals_overview(journals: Sequence[JournalSummary]) -> str:
    """Список журналов: название с пометкой вида и средний балл, строки до 50 символов."""
    lines: list[str] = []
    for journal in journals:
        name = journal_display_name(journal.name, journal.type)
        average = f"{journal.average:.2f}" if journal.average is not None else None
        line = _overview_line(name, average)
        if display_width(line) > TABLE_WIDTH:
            # Обрезаем само название, а пометку вида («Л»/«П») сохраняем.
            excess = display_width(line) - TABLE_WIDTH
            base = _truncate(journal.name, max(1, display_width(journal.name) - excess))
            name = journal_display_name(base, journal.type)
            line = _overview_line(name, average)
        lines.append(line)
    return "\n".join(lines)


def format_new_grades(notices: Sequence[NewGradeNotice], translate: Translator | None = None) -> str:
    """Сообщение о новых оценках: заголовок и строки «дата — предмет — значение».

    Одна пачка — одно сообщение: и днём, и в утренней сводке (задачи 3.1–3.2).
    Название журнала приходит из API, поэтому экранируется: в HTML-разметке Telegram
    символы `<`, `>` и `&` сломали бы сообщение.
    """
    t: Callable[[str], str] = translate or _
    lines = [t(n_("notifications.title"))]
    for notice in notices:
        name = journal_display_name(notice.journal_name, notice.journal_type, translate)
        lines.append(
            t(n_("notifications.line")).format(
                date=format_date(notice.date),
                name=html.escape(name),
                value=html.escape(notice.value or EMPTY_CELL),
            ),
        )
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
