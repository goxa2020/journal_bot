import secrets

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline.menu import get_main_menu_keyboard
from bot.services.analytics import analytics
from bot.utils.main_menu import get_main_menu
from bot.utils.misc import n_

WELCOME_VARIANTS = [
    n_("welcome_back_1"),  # "Давно не виделись! 😊"
    n_("welcome_back_2"),  # "Рад тебя снова видеть! 👋"
    n_("welcome_back_3"),  # "Привет еще раз! 🌟"
    n_("welcome_back_4"),  # "С возвращением! 😄"
]

router = Router(name="start")


@router.message(CommandStart())
@analytics.track_event("Sign Up")
async def start_handler(message: Message, session: AsyncSession, new_user: bool = False) -> None:
    """Welcome message."""
    if not message.from_user:
        return

    kb = await get_main_menu_keyboard(session, message.from_user.id)

    if new_user:
        await message.answer(_("first message"), reply_markup=kb)
    else:
        welcome_text = _(secrets.choice(WELCOME_VARIANTS))
        main_text = await get_main_menu(session, message.from_user.id)
        await message.answer(welcome_text + "\n" + main_text, reply_markup=kb)
