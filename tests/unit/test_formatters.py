from __future__ import annotations
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.database.models.sync_log import SyncStatus, SyncType
from bot.services.grade_sync import JournalSyncResult, SyncSummary
from bot.services.grades import GradesService, JournalSummary
from bot.utils.formatters import (
    GRADES_TABLE_WIDTH,
    TABLE_WIDTH,
    format_average,
    format_date,
    format_grades_table,
    format_journals_overview,
    format_last_grade,
    format_sync_summary,
    journal_display_name,
)
from bot.utils.main_menu import get_main_menu


def test_format_date_pads_day_and_month() -> None:
    assert format_date(date(2026, 2, 3)) == "03.02.2026"


def test_format_last_grade(ru_locale) -> None:
    text = format_last_grade("5", "Математика", date(2026, 2, 3))

    assert "5" in text
    assert "Математика" in text
    assert "03.02.2026" in text


async def test_main_menu_without_grades_shows_empty_state(monkeypatch, ru_locale) -> None:
    monkeypatch.setattr("bot.utils.main_menu.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr(GradesService, "get_last_grade", AsyncMock(return_value=None))

    assert await get_main_menu(AsyncMock(), 1) == "Оценки не найдены"


async def test_main_menu_shows_real_last_grade(monkeypatch, ru_locale) -> None:
    monkeypatch.setattr("bot.utils.main_menu.is_authorized", AsyncMock(return_value=True))
    monkeypatch.setattr(
        GradesService,
        "get_last_grade",
        AsyncMock(return_value=("4", "Физика", date(2026, 3, 10))),
    )

    text = await get_main_menu(AsyncMock(), 1)

    assert "4" in text
    assert "Физика" in text
    assert "10.03.2026" in text


async def test_main_menu_for_unauthorized_user_shows_start_text(monkeypatch, ru_locale) -> None:
    monkeypatch.setattr("bot.utils.main_menu.is_authorized", AsyncMock(return_value=False))

    text = await get_main_menu(AsyncMock(), 1)

    assert "Привет" in text


def _grade(
    *,
    hour: int,
    value: str,
    is_mark: bool = False,
    is_pass: bool = False,
    lesson_date: date | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        date=lesson_date or date(2024, 9, 30),
        hour_number=hour,
        value=value,
        is_mark=is_mark,
        is_pass=is_pass,
        number_value=int(value) if is_mark and value.isdigit() else None,
    )


def _table_lines(text: str) -> list[str]:
    body = text.split("<pre>", 1)[1].split("</pre>", 1)[0]
    return body.splitlines()


def test_long_title_does_not_break_table(ru_locale) -> None:
    title = "Очень длинное название дисциплины, которое заведомо не влезает в строку таблицы"
    text = format_grades_table(title, [_grade(hour=1, value="4", is_mark=True)])

    lines = _table_lines(text)
    assert all(len(line) == GRADES_TABLE_WIDTH for line in lines)
    assert "<b>" in text


def test_empty_values_do_not_break_columns(ru_locale) -> None:
    text = format_grades_table("Физика", [_grade(hour=2, value="", is_mark=False)])
    lines = _table_lines(text)

    assert all(len(line) == GRADES_TABLE_WIDTH for line in lines)
    assert "—" in lines[2]


def test_table_has_one_value_column_without_subject_and_pair(ru_locale) -> None:
    text = format_grades_table(
        "Физика",
        [
            _grade(hour=1, value="4", is_mark=True),
            _grade(hour=2, value="Н", is_pass=True),
        ],
    )
    lines = _table_lines(text)
    body = "\n".join(lines)

    assert "4" in lines[2]
    assert "Н" in lines[3]
    assert "Физика" not in body
    assert "Пара" not in body
    assert all(len(line) == GRADES_TABLE_WIDTH for line in lines)


def test_journal_display_name_adds_type_suffix(ru_locale) -> None:
    assert journal_display_name("Английский язык", "Лек") == "Английский язык Л"
    assert journal_display_name("Английский язык", "Пр") == "Английский язык П"
    assert journal_display_name("Английский язык", "Лаб") == "Английский язык Лаб"
    assert journal_display_name("Английский язык", "") == "Английский язык"


def test_average_formatting(ru_locale) -> None:
    assert "4.25" in format_average(4.25)
    assert "—" in format_average(None)


def test_journals_overview_truncates_long_names_to_50(ru_locale) -> None:
    journals = [
        JournalSummary(
            id=1,
            name="Очень длинное название предмета, которое точно не влезет в строку списка",
            teacher_name="Преподавателев П.П.",
            type="Лек",
            grades_count=3,
            average=4.5,
        ),
    ]

    text = format_journals_overview(journals)

    assert "…" in text
    assert "4.50" in text
    assert text.endswith(" Л — 4.50")
    assert all(len(line) <= TABLE_WIDTH for line in text.splitlines())


def test_sync_summary_without_errors(ru_locale) -> None:
    summary = SyncSummary(
        user_id=1,
        sync_type=SyncType.MANUAL,
        status=SyncStatus.SUCCESS,
        new_grades=2,
        updated_grades=1,
    )

    text = format_sync_summary(summary)

    assert "2" in text
    assert "1" in text
    assert "ошиб" not in text.lower()


def test_sync_summary_lists_failed_journals(ru_locale) -> None:
    summary = SyncSummary(
        user_id=1,
        sync_type=SyncType.MANUAL,
        status=SyncStatus.FAILED,
        new_grades=0,
        updated_grades=0,
        journals=[
            JournalSyncResult(journal_id=1, name="Физика", error="parse"),
            JournalSyncResult(journal_id=2, name="Математика"),
        ],
        error_codes=["parse"],
    )

    text = format_sync_summary(summary)

    assert "Физика" in text
    assert "Математика" not in text


@pytest.mark.parametrize("count", [0, 1, 5])
def test_journals_overview_empty_list_is_empty_string(count: int, ru_locale) -> None:
    journals = [
        JournalSummary(
            id=index,
            name=f"Предмет {index}",
            teacher_name="",
            type="Лек",
            grades_count=0,
            average=None,
        )
        for index in range(count)
    ]

    text = format_journals_overview(journals)
    assert text.count("\n") == max(count - 1, 0)
