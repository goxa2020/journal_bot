from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.grades import GradesService
from bot.services.users import is_authorized
from bot.utils.formatters import format_last_grade


async def get_main_menu(session: AsyncSession, user_id: int) -> str:
    """Возвращает главное меню с проверкой авторизации и последней оценкой."""
    if not await is_authorized(session, user_id):
        return _("first message")

    last_grade = await GradesService.get_last_grade(session, user_id)
    if last_grade is None:
        return _("last_grade.none")

    return format_last_grade(*last_grade)
