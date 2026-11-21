"""Экран `/grades`: рендер из БД, пустые состояния и навигация (задача 2.8)."""

from __future__ import annotations
from datetime import date
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.callback.grades import JOURNAL_PREFIX, grades_back_to_list, grades_show_journal
from bot.handlers.message.grades import grades_command, render_journal, render_journals
from bot.services.grades import GradesService, JournalSummary

if TYPE_CHECKING:
    import pytest


def _summary(*, journal_id: int = 1, average: float | None = 4.5) -> JournalSummary:
    return JournalSummary(
        id=journal_id,
        name="Программирование",
        teacher_name="Преподавателев П.П.",
        type="Лек",
        grades_count=2,
        average=average,
    )


async def test_render_journals_empty_state(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    monkeypatch.setattr(GradesService, "list_journals", AsyncMock(return_value=[]))

    text, keyboard = await render_journals(AsyncMock(), 1)

    assert "Журналов пока нет" in text
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "update" in callbacks


async def test_render_journals_lists_titles(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    monkeypatch.setattr(GradesService, "list_journals", AsyncMock(return_value=[_summary()]))

    text, keyboard = await render_journals(AsyncMock(), 1)

    assert "Программирование" in text
    assert "4.50" in text
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert f"{JOURNAL_PREFIX}1" in callbacks


async def test_render_journal_unknown_returns_none(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    monkeypatch.setattr(GradesService, "get_journal_summary", AsyncMock(return_value=None))

    assert await render_journal(AsyncMock(), 1, 999) is None


async def test_render_journal_empty_grades(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    monkeypatch.setattr(GradesService, "get_journal_summary", AsyncMock(return_value=_summary()))
    monkeypatch.setattr(GradesService, "get_journal_grades", AsyncMock(return_value=[]))

    rendered = await render_journal(AsyncMock(), 1, 1)

    assert rendered is not None
    text, keyboard = rendered
    assert "Оценок пока нет" in text
    assert "Обновить" in text
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "update" in callbacks


async def test_render_journal_table(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    grade = SimpleNamespace(
        date=date(2024, 9, 30),
        hour_number=1,
        value="4",
        is_mark=True,
        is_pass=False,
        number_value=4,
    )
    monkeypatch.setattr(GradesService, "get_journal_summary", AsyncMock(return_value=_summary()))
    monkeypatch.setattr(GradesService, "get_journal_grades", AsyncMock(return_value=[grade]))

    rendered = await render_journal(AsyncMock(), 1, 1)

    assert rendered is not None
    text, _keyboard = rendered
    assert "<pre>" in text
    assert "Средний балл" in text
    assert "Н — отсутствовал" in text


async def test_grades_command_for_unauthorized_user_asks_to_login(
    monkeypatch: pytest.MonkeyPatch,
    ru_locale,
) -> None:
    message = MagicMock()
    message.from_user.id = 1
    message.answer = AsyncMock()
    monkeypatch.setattr("bot.handlers.message.grades.is_authorized", AsyncMock(return_value=False))
    monkeypatch.setattr("bot.handlers.message.grades.get_main_menu_keyboard", AsyncMock(return_value=None))
    monkeypatch.setattr("bot.handlers.message.grades.get_main_menu", AsyncMock(return_value="меню"))

    await grades_command(message, AsyncMock())

    message.answer.assert_awaited_once()
    assert "/start" in message.answer.await_args.args[0]


async def test_callback_for_unknown_journal_shows_alert_not_traceback(
    monkeypatch: pytest.MonkeyPatch,
    ru_locale,
) -> None:
    monkeypatch.setattr("bot.handlers.callback.grades.Message", MagicMock)
    callback = MagicMock()
    callback.from_user.id = 1
    callback.data = f"{JOURNAL_PREFIX}999"
    callback.message = MagicMock()
    callback.answer = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.grades.render_journal", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "bot.handlers.callback.grades.render_journals",
        AsyncMock(return_value=("список", None)),
    )
    edit = AsyncMock()
    monkeypatch.setattr("bot.handlers.callback.grades.edit_bot_message", edit)

    await grades_show_journal(callback, AsyncMock())

    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs["show_alert"] is True
    edit.assert_awaited_once()


async def test_callback_back_to_list_edits_same_message(monkeypatch: pytest.MonkeyPatch, ru_locale) -> None:
    monkeypatch.setattr("bot.handlers.callback.grades.Message", MagicMock)
    callback = MagicMock()
    callback.from_user.id = 1
    callback.message = MagicMock()
    callback.message.message_id = 77
    callback.answer = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.callback.grades.render_journals",
        AsyncMock(return_value=("список", None)),
    )
    edit = AsyncMock(return_value=77)
    monkeypatch.setattr("bot.handlers.callback.grades.edit_bot_message", edit)

    await grades_back_to_list(callback, AsyncMock())

    edit.assert_awaited_once_with(callback.message, 77, "список", None)
    callback.answer.assert_awaited_once()
