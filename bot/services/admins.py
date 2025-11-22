from __future__ import annotations
from typing import TYPE_CHECKING

from loguru import logger

from bot.database.database import sessionmaker
from bot.services.users import get_admins_ids

if TYPE_CHECKING:
    from aiogram import Bot


async def send_to_admins(bot: Bot, message: str) -> None:
    async with sessionmaker() as session:
        admins_ids = await get_admins_ids(session)
    logger.info(f"Отправка сообщения администраторам")
    for admin_id in admins_ids:
        await bot.send_message(chat_id=admin_id, text=message)
