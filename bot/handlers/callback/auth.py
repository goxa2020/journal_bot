from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.message.auth import FormAuth
from bot.keyboards.reply import get_cancel_keyboard
from bot.services.users import is_authorized

router = Router()


@router.callback_query(F.data == "auth_start")
async def auth_start(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not isinstance(callback.message, Message):
        return
    user_id = callback.from_user.id
    if await is_authorized(session, user_id):
        await callback.answer("Вы уже авторизованы.")
        return

    await callback.message.answer(
        _("auth.enter_login"),
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(FormAuth.login)
    await callback.answer()
