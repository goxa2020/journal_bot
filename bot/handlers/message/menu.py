from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline.menu import get_main_menu

router = Router(name="menu")

@router.message(Command(commands=["menu", "main"]))
async def menu_handler(message: Message, session: AsyncSession) -> None:
    if not message.from_user:
        return

    text = _("title main keyboard")

    msg_to_remove = await message.answer(
        text, reply_markup=ReplyKeyboardRemove()
    )

    await msg_to_remove.delete()

    kb = await get_main_menu(session, message.from_user.id)
    await message.answer(text, reply_markup=kb)
