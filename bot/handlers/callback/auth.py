from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _

from bot.handlers.message.auth import FormAuth
from bot.keyboards.inline.auth import get_cancel_inline_keyboard
from bot.keyboards.inline.menu import get_main_menu_keyboard
from bot.services.users import is_authorized
from bot.utils.main_menu import get_main_menu

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="auth_callback")


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

    sent_message = await callback.message.answer(
        _("auth.enter_login"),
        reply_markup=get_cancel_inline_keyboard(),
    )
    await state.update_data(bot_message_id=sent_message.message_id)
    await state.set_state(FormAuth.login)
    await callback.answer()


@router.callback_query(F.data == "auth_cancel")
async def auth_cancel(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not isinstance(callback.message, Message):
        return

    await state.clear()

    kb = await get_main_menu_keyboard(session, callback.from_user.id)
    text = await get_main_menu(session, callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb)

    await callback.answer(_("cancelled"))
