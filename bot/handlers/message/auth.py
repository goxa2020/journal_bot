from __future__ import annotations
import re
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.utils.i18n import gettext as _

from bot.keyboards.inline.menu import get_main_menu
from bot.keyboards.reply import get_cancel_keyboard
from bot.services.users import set_edu_credentials

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
    await state.clear()
    await message.answer(_("cancelled"), reply_markup=ReplyKeyboardRemove())
    kb = await get_main_menu(session, message.from_user.id)
    await message.answer(_("title main keyboard"), reply_markup=kb)


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
    if not message.text:
        await message.answer(
            _("auth.enter_login_invalid"),
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

    await set_edu_credentials(session, message.from_user.id, login, password)

    await state.clear()
    await message.answer(_("auth.success"), reply_markup=ReplyKeyboardRemove())
    kb = await get_main_menu(session, message.from_user.id)
    await message.answer(_("title main keyboard"), reply_markup=kb)
