"""Экран `/grades`: список журналов и таблица оценок (задача 2.8).

Хендлер не ходит в сеть: только БД. Данные забирает Celery-задача синхронизации
(2.6), а здесь они лишь читаются и форматируются.
"""

from __future__ import annotations
import html
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.utils.i18n import gettext as _

from bot.keyboards.inline.grades import (
    get_grades_empty_keyboard,
    get_grades_keyboard,
    get_journals_keyboard,
)
from bot.keyboards.inline.menu import get_main_menu_keyboard
from bot.services.grades import GradesService
from bot.services.users import is_authorized
from bot.utils.formatters import (
    format_average,
    format_grades_table,
    format_journals_overview,
    journal_display_name,
)
from bot.utils.main_menu import get_main_menu

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup, Message
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="grades")


async def render_journals(session: AsyncSession, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура списка журналов пользователя."""
    journals = await GradesService.list_journals(session, user_id)
    if not journals:
        return _("grades.no_journals"), get_journals_keyboard([])
    text = "\n\n".join(
        (
            _("grades.title"),
            _("grades.choose_journal"),
            format_journals_overview(journals),
        ),
    )
    return text, get_journals_keyboard(journals)


async def render_journal(
    session: AsyncSession,
    user_id: int,
    journal_id: int,
) -> tuple[str, InlineKeyboardMarkup] | None:
    """Текст и клавиатура одного журнала; `None` — журнала у пользователя нет."""
    summary = await GradesService.get_journal_summary(session, user_id, journal_id)
    if summary is None:
        return None

    grades = await GradesService.get_journal_grades(session, user_id, journal_id)
    display_name = journal_display_name(summary.name, summary.type)
    if not grades:
        text = "\n\n".join(
            (
                f"<b>{html.escape(display_name)}</b>",
                _("grades.empty_journal"),
                _("sync.hint_update"),
            ),
        )
        return text, get_grades_empty_keyboard()

    text = "\n\n".join(
        (
            format_grades_table(display_name, grades),
            format_average(summary.average),
        ),
    )
    return text, get_grades_keyboard()


@router.message(Command("grades"))
async def grades_command(message: Message, session: AsyncSession) -> None:
    """Показать оценки из БД; если пользователь не вошёл — позвать войти."""
    if not message.from_user:
        return
    user_id = message.from_user.id

    if not await is_authorized(session, user_id):
        kb = await get_main_menu_keyboard(session, user_id)
        text = _("grades.login_required") + "\n\n" + await get_main_menu(session, user_id)
        await message.answer(text, reply_markup=kb)
        return

    text, kb = await render_journals(session, user_id)
    await message.answer(text, reply_markup=kb)
