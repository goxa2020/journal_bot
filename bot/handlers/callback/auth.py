from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _

from bot.handlers.message.auth import FormAuth, run_auth_attempt, show_main_menu
from bot.keyboards.inline.auth import get_cancel_inline_keyboard
from bot.services.auth import edit_bot_message
from bot.services.users import is_authorized

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

    # Правим сообщение на месте: отдельное сообщение на каждый «Войти» плодило
    # копии меню, которые потом приходилось удалять.
    bot_message_id = await edit_bot_message(
        callback.message,
        callback.message.message_id,
        _("auth.enter_login"),
        get_cancel_inline_keyboard(),
    )
    await state.update_data(bot_message_id=bot_message_id, password_enc=None)
    await state.set_state(FormAuth.login)
    await callback.answer()


@router.callback_query(F.data == "auth_retry")
async def auth_retry(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not isinstance(callback.message, Message):
        return

    await callback.answer()
    # Логин и пароль уже в состоянии; если их там нет — обработчик вернёт к вводу логина
    await run_auth_attempt(callback.message, session, state, callback.from_user.id)


@router.callback_query(F.data == "auth_cancel")
async def auth_cancel(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not isinstance(callback.message, Message):
        return

    await state.clear()

    # Возвращаем меню в то же сообщение, из которого начали вход
    await show_main_menu(
        callback.message,
        session,
        callback.from_user.id,
        callback.message.message_id,
    )

    await callback.answer(_("cancelled"))
