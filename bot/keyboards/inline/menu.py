from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.users import is_authorized


async def get_main_menu(session: AsyncSession, user_id: int) -> InlineKeyboardMarkup:
    """Главное меню с проверкой авторизации."""
    builder = InlineKeyboardBuilder()

    builder.button(text=_("info button"), callback_data="info")

    authorized = await is_authorized(session, user_id)

    if authorized:
        builder.button(text=_("sync_btn"), callback_data="sync")
        builder.button(text=_("stats_btn"), callback_data="stats")
    else:
        builder.button(text=_("auth.menu_btn"), callback_data="auth_start")

    builder.adjust(1, repeat=True)

    return builder.as_markup()
