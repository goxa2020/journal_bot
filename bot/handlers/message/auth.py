from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.utils.i18n import gettext as _

from bot.keyboards.inline.auth import get_cancel_inline_keyboard
from bot.keyboards.inline.menu import get_main_menu_keyboard
from bot.services.api_client import EduUnavailableError
from bot.services.auth import edit_bot_message, handle_auth_login, handle_auth_password
from bot.utils.main_menu import get_main_menu

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="auth")


class FormAuth(StatesGroup):
    login = State()
    password = State()


@router.message(Command("cancel"))
@router.message(lambda message: message.text == _("cancel_btn"))
async def cancel_handler(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not message.from_user:
        return

    await state.clear()
    await message.answer(_("cancelled"), reply_markup=ReplyKeyboardRemove())
    kb = await get_main_menu_keyboard(session, message.from_user.id)
    text = await get_main_menu(session, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.message(StateFilter(FormAuth.login))
async def process_login(
    message: Message,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    bot_message_id = data.get("bot_message_id")

    # Удаляем сообщение пользователя
    await message.delete()

    # Обрабатываем логин через сервис
    new_data, success = await handle_auth_login(message.text, data)
    if not success:
        new_bot_message_id = await edit_bot_message(
            message,
            bot_message_id,
            _("auth.enter_login_invalid"),
            get_cancel_inline_keyboard(),
        )
        await state.update_data(bot_message_id=new_bot_message_id)
        return

    await state.set_data(new_data)
    login = new_data["login"]

    new_bot_message_id = await edit_bot_message(
        message,
        bot_message_id,
        _("auth.enter_pass_with_login").format(login=login),
        get_cancel_inline_keyboard(),
    )
    await state.update_data(bot_message_id=new_bot_message_id)
    await state.set_state(FormAuth.password)


@router.message(StateFilter(FormAuth.password))
async def process_password(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not message.from_user:
        return

    data = await state.get_data()
    bot_message_id = data.get("bot_message_id")

    # Удаляем сообщение пользователя
    await message.delete()

    if not message.text or len(message.text.strip()) == 0:
        new_bot_message_id = await edit_bot_message(
            message,
            bot_message_id,
            _("auth.enter_pass_invalid"),
            get_cancel_inline_keyboard(),
        )
        await state.update_data(bot_message_id=new_bot_message_id)
        return

    password = message.text.strip()
    login = data["login"]

    # Редактируем сообщение на "Авторизация запущена..."
    bot_message_id = await edit_bot_message(
        message,
        bot_message_id,
        _("auth.auth_started"),
        None,
    )
    await state.update_data(bot_message_id=bot_message_id)

    # Выполняем авторизацию через сервис
    try:
        success, __ = await handle_auth_password(
            user_id=message.from_user.id,
            login=login,
            password=password,
            session=session,
        )
    except EduUnavailableError:
        bot_message_id = await edit_bot_message(
            message,
            bot_message_id,
            _("auth.unavailable"),
            get_cancel_inline_keyboard(),
        )
        await state.update_data(bot_message_id=bot_message_id)
        await state.set_state(FormAuth.password)
        return

    if not success:
        bot_message_id = await edit_bot_message(
            message,
            bot_message_id,
            _("auth.failed"),
            get_cancel_inline_keyboard(),
        )
        await state.update_data(bot_message_id=bot_message_id)
        await state.set_state(FormAuth.login)
        return

    # Успешная авторизация
    await edit_bot_message(
        message,
        bot_message_id,
        _("auth.success"),
        None,
    )

    await state.clear()
    kb = await get_main_menu_keyboard(session, message.from_user.id)
    text = await get_main_menu(session, message.from_user.id)
    await message.answer(text, reply_markup=kb)
