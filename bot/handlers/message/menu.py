from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline.menu import get_main_menu

router = Router(name="menu")


@router.message(Command(commands=["menu", "main"]))
async def menu_handler(message: Message, session: AsyncSession) -> None:
    """Return main menu."""
    kb = await get_main_menu(session, message.from_user.id)
    await message.answer(_("title main keyboard"), reply_markup=kb)
