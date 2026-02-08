from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.grades import GradesService
from bot.services.users import is_authorized


async def get_main_menu(session: AsyncSession, user_id: int) -> str:
    """Возвращает главное меню с проверкой авторизации."""
    authorized = is_authorized(session, user_id)
    if authorized:
        last_grade = await GradesService.get_recent(session, user_id, 1)

        return _("last_grade").format(4, "Математика", "30.02.2026") if last_grade else _("last_grade.none")
    return _("first message")
