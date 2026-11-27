"""Callback-обработчики экрана «Режим ожидания» (фаза 5, задача 5.1).

Один экран — одно сообщение: открытие, продление, выключение и возврат в меню правят
его `edit_message_text`, новых сообщений не появляется (та же дисциплина, что у
`/settings`). Любое нажатие обязано ответить `callback.answer()` ровно один раз —
иначе на кнопке навсегда остаётся спиннер; поэтому ответ стоит в `finally`, а ветки,
которым нужен всплывающий текст, помечают, что уже ответили.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _

from bot.core.config import settings
from bot.core.loader import redis_client
from bot.handlers.message.auth import show_main_menu
from bot.keyboards.inline.watch import (
    CALLBACK_EXTEND,
    CALLBACK_MENU,
    CALLBACK_OFF,
    CALLBACK_REFRESH,
    CALLBACK_WATCH,
    get_watch_keyboard,
)
from bot.services.auth import edit_bot_message
from bot.services.watch import REASON_NOT_AUTHENTICATED, WatchModeService, WatchState

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="watch_callback")


def _service(session: AsyncSession) -> WatchModeService:
    """Сервис режима с общим Redis-клиентом процесса бота и сроком из настроек."""
    return WatchModeService(
        session=session,
        redis=redis_client,
        minutes=settings.WATCH_MODE_MINUTES,
    )


def render_watch_screen(state: WatchState) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура экрана для текущего состояния режима."""
    if state.active:
        text = "\n".join(
            (
                _("watch.title_on"),
                _("watch.left").format(minutes=state.minutes_left),
                "",
                _("watch.hint_on").format(tick=settings.WATCH_MODE_TICK_MINUTES),
            ),
        )
    else:
        text = "\n".join(
            (
                _("watch.title_off"),
                "",
                _("watch.hint_off").format(
                    tick=settings.WATCH_MODE_TICK_MINUTES,
                    minutes=settings.WATCH_MODE_MINUTES,
                ),
            ),
        )
    return text, get_watch_keyboard(active=state.active)


async def _render(callback: CallbackQuery, state: WatchState) -> None:
    """Показать экран в том же сообщении (если это сообщение бота, а не inline-режим)."""
    if not isinstance(callback.message, Message):
        return
    text, kb = render_watch_screen(state)
    await edit_bot_message(callback.message, callback.message.message_id, text, kb)


async def _refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    """Перерисовать экран по текущему состоянию."""
    state = await _service(session).get_state(callback.from_user.id)
    await _render(callback, state)


async def _back_to_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    if isinstance(callback.message, Message):
        await show_main_menu(callback.message, session, callback.from_user.id, callback.message.message_id)


@router.callback_query(F.data == CALLBACK_WATCH)
async def watch_open(callback: CallbackQuery, session: AsyncSession) -> None:
    """Кнопка «Режим ожидания»: показать экран или включить режим, если он выключен."""
    answered = False
    try:
        service = _service(session)
        state = await service.get_state(callback.from_user.id)
        if state.active:
            await _render(callback, state)
            return

        outcome = await service.enable(callback.from_user.id)
        if outcome.reason == REASON_NOT_AUTHENTICATED:
            await _back_to_menu(callback, session)
            answered = True
            await callback.answer(_("watch.not_authenticated"), show_alert=True)
            return

        await _render(callback, outcome.state)
        answered = True
        await callback.answer(_("watch.enabled_alert"))
    finally:
        if not answered:
            await callback.answer()


@router.callback_query(F.data == CALLBACK_EXTEND)
async def watch_extend(callback: CallbackQuery, session: AsyncSession) -> None:
    """Продлить режим: новые 30 минут от текущего момента."""
    answered = False
    try:
        outcome = await _service(session).enable(callback.from_user.id)
        if outcome.reason == REASON_NOT_AUTHENTICATED:
            await _back_to_menu(callback, session)
            answered = True
            await callback.answer(_("watch.not_authenticated"), show_alert=True)
            return

        await _render(callback, outcome.state)
        answered = True
        await callback.answer(_("watch.enabled_alert"))
    finally:
        if not answered:
            await callback.answer()


@router.callback_query(F.data == CALLBACK_OFF)
async def watch_off(callback: CallbackQuery, session: AsyncSession) -> None:
    """Выключить режим досрочно и показать выключенный экран."""
    answered = False
    try:
        await _service(session).disable(callback.from_user.id)
        await _refresh(callback, session)
        answered = True
        await callback.answer(_("watch.disabled_alert"))
    finally:
        if not answered:
            await callback.answer()


@router.callback_query(F.data == CALLBACK_REFRESH)
async def watch_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    """Обновить остаток времени, не меняя состояние."""
    try:
        await _refresh(callback, session)
    finally:
        await callback.answer()


@router.callback_query(F.data == CALLBACK_MENU)
async def watch_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """«Главное меню»: вернуть меню в то же сообщение."""
    try:
        await _back_to_menu(callback, session)
    finally:
        await callback.answer()
