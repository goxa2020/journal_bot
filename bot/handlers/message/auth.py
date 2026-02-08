from __future__ import annotations
import re
from typing import TYPE_CHECKING, Any

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.utils.i18n import gettext as _

from bot.keyboards.inline.menu import get_main_menu_keyboard
from bot.keyboards.reply import get_cancel_keyboard
from bot.services.api_client import get_auth_data
from bot.services.auth import authenticate_user
from bot.services.users import set_edu_credentials, set_user_data
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
    if not message.text:
        await message.answer(
            _("auth.enter_login_invalid"),
            reply_markup=get_cancel_keyboard(),
        )
        return

    login = message.text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", login):
        await message.answer(
            _("auth.enter_login_invalid"),
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(login=login)
    await message.answer(
        _("auth.enter_pass"),
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(FormAuth.password)


@router.message(StateFilter(FormAuth.password))
async def process_password(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not message.from_user:
        return

    if not message.text:
        await message.answer(
            _("auth.enter_pass_invalid"),
            reply_markup=get_cancel_keyboard(),
        )
        return

    password = message.text.strip()
    if len(password) == 0:
        await message.answer(
            _("auth.enter_pass_invalid"),
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    login = data["login"]

    access_token = await authenticate_user(login, password)

    if not access_token:
        await message.answer(
            _("auth.failed"),
            reply_markup=get_cancel_keyboard(),
        )

        await state.set_state(FormAuth.login)
        return

    await message.answer(_("auth.success"), reply_markup=ReplyKeyboardRemove())

    await set_edu_credentials(session, message.from_user.id, login, password)

    auth_data = await get_auth_data(access_token)
    user_data_raw = auth_data.get("user")
    if user_data_raw is None:
        await message.answer(_("auth.failed"), reply_markup=ReplyKeyboardRemove())
        await state.set_state(FormAuth.login)
        return
    user_data: dict[str, Any] = user_data_raw

    await set_user_data(
        session=session,
        user_id=message.from_user.id,
        edu_user_id=user_data.get("userID"),
        group_id=user_data.get("groupID"),
        group_name=user_data.get("group"),
        full_name=user_data.get("fio"),
        is_authenticated=True,
    )

    await state.clear()
    kb = await get_main_menu_keyboard(session, message.from_user.id)
    text = await get_main_menu(session, message.from_user.id)
    await message.answer(text, reply_markup=kb)
