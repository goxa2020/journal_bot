from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline.menu import get_main_menu
from bot.services.analytics import analytics

router = Router(name="start")


@router.message(CommandStart())
@analytics.track_event("Sign Up")
async def start_handler(message: Message, session: AsyncSession) -> None:
    """Welcome message."""
    kb = await get_main_menu(session, message.from_user.id)
    await message.answer(_("first message"), reply_markup=kb)
