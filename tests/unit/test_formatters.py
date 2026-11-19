from __future__ import annotations
from datetime import date
from unittest.mock import AsyncMock

from bot.services.grades import GradesService
from bot.utils.formatters import format_date, format_last_grade
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
