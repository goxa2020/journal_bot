"""`/sync` и кнопка «Обновить» (задача 2.7).

Хендлер только ставит задачу: сетевых вызовов edu-tpi здесь нет. Повторное нажатие не
плодит задачи — сначала проверяется lock синхронизации и ключ `sync:queued`, который
живёт 30 секунд и защищает от двойного нажатия до старта воркера.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.utils.i18n import gettext as _

from bot.cache.redis import build_key
from bot.core.loader import redis_client as loader_redis_client
from bot.keyboards.inline.menu import get_main_menu_keyboard
from bot.services.users import is_authorized
from bot.tasks.sync import sync_user_manual
from bot.utils.main_menu import get_main_menu

if TYPE_CHECKING:
    from aiogram.types import Message
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="sync")

SYNC_QUEUE_TTL_SECONDS = 30


async def request_manual_sync(user_id: int, redis: Redis) -> bool:
    """Поставить задачу, если по пользователю ещё ничего не идёт.

    Возвращает `False`, если синхронизация уже идёт или уже поставлена.
    """
    if await redis.exists(build_key("sync:lock", user_id)):
        return False
    queued_key = build_key("sync:queued", user_id)
    if not await redis.set(queued_key, "1", nx=True, ex=SYNC_QUEUE_TTL_SECONDS):
        return False

    try:
        sync_user_manual.delay(user_id)
    except Exception:
        # Задача не встала — не держим пользователя в «уже идёт» до истечения TTL.
        await redis.delete(queued_key)
        raise
    return True


def get_redis_client() -> Redis:
    """Redis процесса бота; вынесено в функцию, чтобы тесты могли подменить клиент."""
    return loader_redis_client


@router.message(Command("sync"))
async def sync_command(message: Message, session: AsyncSession) -> None:
    """Обновить оценки вручную."""
    if not message.from_user:
        return
    user_id = message.from_user.id

    if not await is_authorized(session, user_id):
        kb = await get_main_menu_keyboard(session, user_id)
        text = _("sync.auth_required") + "\n\n" + await get_main_menu(session, user_id)
        await message.answer(text, reply_markup=kb)
        return

    started = await request_manual_sync(user_id, get_redis_client())
    await message.answer(_("sync.started") if started else _("sync.already_running"))
