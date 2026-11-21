from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.i18n import gettext as _
from loguru import logger

from bot.core.encryption import decrypt, encrypt
from bot.core.errors import EduUnavailableError
from bot.core.loader import redis_client
from bot.keyboards.inline.auth import get_auth_error_keyboard, get_cancel_inline_keyboard
from bot.keyboards.inline.menu import get_main_menu_keyboard
from bot.services.auth import delete_token, edit_bot_message, handle_auth_login, handle_auth_password
from bot.services.users import logout_user
from bot.tasks.sync import sync_user_after_login
from bot.utils.main_menu import get_main_menu

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext
    from aiogram.types import Message
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="auth")


class FormAuth(StatesGroup):
    login = State()
    password = State()


async def show_main_menu(
    message: Message,
    session: AsyncSession,
    user_id: int,
    bot_message_id: int | None,
    prefix: str = "",
) -> None:
    """Заменить сообщение бота на главное меню, не отправляя новое."""
    kb = await get_main_menu_keyboard(session, user_id)
    text = await get_main_menu(session, user_id)
    await edit_bot_message(message, bot_message_id, prefix + text, kb)


async def _restart_login(
    message: Message,
    state: FSMContext,
    bot_message_id: int | None,
) -> None:
    """Вернуть пользователя к вводу логина, если учётных данных в состоянии нет."""
    bot_message_id = await edit_bot_message(
        message,
        bot_message_id,
        _("auth.enter_login"),
        get_cancel_inline_keyboard(),
    )
    await state.update_data(bot_message_id=bot_message_id, password_enc=None)
    await state.set_state(FormAuth.login)


async def run_auth_attempt(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    user_id: int,
) -> None:
    """Одна попытка входа: общий путь для ввода пароля и для кнопки «Ещё раз».

    Логин и пароль берутся из состояния: пароль там лежит только шифротекстом,
    поэтому повтор не требует, чтобы пользователь вводил его заново.
    """
    data = await state.get_data()
    bot_message_id = data.get("bot_message_id")
    login = data.get("login")
    token = data.get("password_enc")
    password = decrypt(token) if isinstance(token, str) else None

    if not login or not password:
        # Состояние истекло (рестарт Redis) или ключ шифрования сменился
        await _restart_login(message, state, bot_message_id)
        return

    bot_message_id = await edit_bot_message(message, bot_message_id, _("auth.auth_started"), None)
    await state.update_data(bot_message_id=bot_message_id)

    try:
        success, __ = await handle_auth_password(
            user_id=user_id,
            login=login,
            password=password,
            session=session,
        )
    except EduUnavailableError:
        bot_message_id = await edit_bot_message(
            message,
            bot_message_id,
            _("auth.unavailable"),
            get_auth_error_keyboard(),
        )
        await state.update_data(bot_message_id=bot_message_id)
        await state.set_state(FormAuth.password)
        return

    if not success:
        # Пароль не подошёл — повторять его бессмысленно, начинаем с логина.
        bot_message_id = await edit_bot_message(
            message,
            bot_message_id,
            _("auth.failed"),
            get_cancel_inline_keyboard(),
        )
        await state.update_data(bot_message_id=bot_message_id, password_enc=None)
        await state.set_state(FormAuth.login)
        return

    # Успех: одно сообщение вместо «успех» + новое меню.
    await state.clear()
    await show_main_menu(
        message,
        session,
        user_id,
        bot_message_id,
        prefix=f"{_('auth.success')}\n\n",
    )
    # Первая синхронизация — в фоне: пользователь не ждёт обхода журналов.
    # Недоступный брокер не должен ломать уже успешный вход.
    try:
        sync_user_after_login.delay(user_id)
    except Exception:  # noqa: BLE001 — вход важнее фоновой задачи
        logger.exception("sync after login enqueue failed user={}", user_id)


@router.message(Command("logout"))
async def logout_handler(
    message: Message,
    session: AsyncSession,
) -> None:
    """Выйти из edu-tpi: токен, шифрованные креды и флаг авторизации."""
    if not message.from_user:
        return
    user_id = message.from_user.id

    await delete_token(redis_client, user_id)
    await logout_user(session, user_id)

    kb = await get_main_menu_keyboard(session, user_id)
    text = _("logout.done") + "\n\n" + await get_main_menu(session, user_id)
    await message.answer(text, reply_markup=kb)


@router.message(Command("cancel"))
async def cancel_handler(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not message.from_user:
        return

    await state.clear()
    await message.answer(_("cancelled"))
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
    login = data.get("login")

    # Удаляем сообщение пользователя: пароль не должен оставаться в чате
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

    if not login:
        await _restart_login(message, state, bot_message_id)
        return

    # Пароль нужен кнопке «Ещё раз». В состоянии он лежит только шифротекстом:
    # открытый пароль не попадает ни в Redis, ни в логи.
    await state.update_data(password_enc=encrypt(message.text.strip()))

    await run_auth_attempt(message, session, state, message.from_user.id)
