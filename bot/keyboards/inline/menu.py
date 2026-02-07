from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.users import is_authorized


async def get_main_menu_keyboard(session: AsyncSession, user_id: int) -> InlineKeyboardMarkup:
    """Главное меню с проверкой авторизации."""
    builder = InlineKeyboardBuilder()

    authorized = await is_authorized(session, user_id)

    if authorized:
        builder.button(text=_("menu.grades_btn"), callback_data="grades")
        builder.button(text=_("menu.stats_btn"), callback_data="stats")

        builder.button(text=_("menu.watch_btn"), callback_data="watch")
        builder.button(text=_("menu.settings_btn"), callback_data="settings")

        builder.button(text=_("menu.export_btn"), callback_data="export")
        builder.button(text=_("menu.help_btn"), callback_data="help")

        builder.button(text=_("menu.update_btn"), callback_data="update")
    else:
        builder.button(text=_("menu.auth_btn"), callback_data="auth_start")
        builder.button(text=_("menu.help_btn"), callback_data="help")

    builder.adjust(2, repeat=True)

    return builder.as_markup()
