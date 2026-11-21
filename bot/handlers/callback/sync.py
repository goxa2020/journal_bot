"""Кнопка «Обновить» в меню и на экране оценок (задача 2.7)."""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _

from bot.handlers.message.auth import show_main_menu
from bot.handlers.message.sync import get_redis_client, request_manual_sync
from bot.services.users import is_authorized

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="sync_callback")


@router.callback_query(F.data == "update")
async def update_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    """Поставить синхронизацию; сводку пришлёт воркер отдельным сообщением."""
    if not isinstance(callback.message, Message):
        return
    user_id = callback.from_user.id

    if not await is_authorized(session, user_id):
        await callback.answer(_("sync.auth_required"), show_alert=True)
        await show_main_menu(callback.message, session, user_id, callback.message.message_id)
        return

    started = await request_manual_sync(user_id, get_redis_client())
    # Короткий toast: не разрушаем таблицу оценок, которую пользователь сейчас смотрит.
    await callback.answer(_("sync.started") if started else _("sync.already_running"))
