from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select, update

from bot.cache.redis import build_key, cached, clear_cache
from bot.core.config import settings
from bot.database.models import UserModel

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from datetime import datetime

    from aiogram.types import User
    from sqlalchemy.ext.asyncio import AsyncSession


async def add_user(
    session: AsyncSession,
    user: User,
    referrer: str | None,
) -> None:
    """Add a new user to the database."""
    user_id: int = user.id
    first_name: str = user.first_name
    last_name: str | None = user.last_name
    username: str | None = user.username
    language_code: str | None = user.language_code
    is_premium: bool = user.is_premium or False

    new_user = UserModel(
        id=user_id,
        first_name=first_name,
        last_name=last_name,
        username=username,
        language_code=language_code,
        is_premium=is_premium,
        referrer=referrer,
    )

    session.add(new_user)
    await session.commit()
    await clear_cache(user_exists, user_id)


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def user_exists(session: AsyncSession, user_id: int) -> bool:
    """Checks if the user is in the database."""
    query = select(UserModel.id).filter_by(id=user_id).limit(1)

    result = await session.execute(query)

    user = result.scalar_one_or_none()
    return bool(user)


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def get_first_name(session: AsyncSession, user_id: int) -> str:
    query = select(UserModel.first_name).filter_by(id=user_id)

    result = await session.execute(query)

    first_name = result.scalar_one_or_none()
    return first_name or ""


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def get_language_code(session: AsyncSession, user_id: int) -> str:
    query = select(UserModel.language_code).filter_by(id=user_id)

    result = await session.execute(query)

    language_code = result.scalar_one_or_none()
    return language_code or ""


async def set_language_code(
    session: AsyncSession,
    user_id: int,
    language_code: str,
) -> None:
    stmt = update(UserModel).where(UserModel.id == user_id).values(language_code=language_code)

    await session.execute(stmt)
    await session.commit()


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def is_admin(session: AsyncSession, user_id: int) -> bool:
    query = select(UserModel.is_admin).filter_by(id=user_id)

    result = await session.execute(query)

    is_admin = result.scalar_one_or_none()
    return bool(is_admin)


async def set_is_admin(session: AsyncSession, user_id: int, is_admin: bool) -> None:
    stmt = update(UserModel).where(UserModel.id == user_id).values(is_admin=is_admin)

    await session.execute(stmt)
    await session.commit()


@cached(key_builder=lambda session: build_key())
async def get_all_users(session: AsyncSession) -> list[UserModel]:
    query = select(UserModel)

    result = await session.execute(query)

    users = result.scalars()
    return list(users)


@cached(key_builder=lambda session: build_key())
async def get_admins_ids(session: AsyncSession) -> list[int]:
    query = select(UserModel.id).filter_by(is_admin=True)

    result = await session.execute(query)

    users = result.scalars()
    return list(users)


@cached(key_builder=lambda session: build_key())
async def get_user_count(session: AsyncSession) -> int:
    query = select(func.count()).select_from(UserModel)

    result = await session.execute(query)

    count = result.scalar_one_or_none() or 0
    return int(count)


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def get_edu_credentials(session: AsyncSession, user_id: int) -> tuple[str | None, str | None]:
    """Получить расшифрованные edu credentials пользователя."""
    query = select(UserModel.edu_username_encrypted, UserModel.edu_password_encrypted).filter_by(id=user_id)

    result = await session.execute(query)
    row = result.fetchone()

    if not row or not row[0] or not row[1]:
        return None, None

    fernet = Fernet(settings.ENCRYPTION_KEY.encode())
    username = None
    password = None
    try:
        username = fernet.decrypt(row[0].encode()).decode()
        password = fernet.decrypt(row[1].encode()).decode()
    except InvalidToken:
        logger.debug("Failed to decrypt edu credentials for user_id=%d", user_id)
    return username, password


async def set_edu_credentials(session: AsyncSession, user_id: int, username: str, password: str) -> None:
    """Сохранить зашифрованные edu credentials пользователя."""
    fernet = Fernet(settings.ENCRYPTION_KEY.encode())
    username_encrypted = fernet.encrypt(username.encode()).decode()
    password_encrypted = fernet.encrypt(password.encode()).decode()

    stmt = (
        update(UserModel)
        .where(UserModel.id == user_id)
        .values(edu_username_encrypted=username_encrypted, edu_password_encrypted=password_encrypted)
    )
    await session.execute(stmt)
    await session.commit()
    await clear_cache(get_edu_credentials, user_id)


async def is_authorized(session: AsyncSession, user_id: int) -> bool:
    """Проверить, авторизован ли пользователь (имеет edu credentials)."""
    username, _ = await get_edu_credentials(session, user_id)
    return username is not None


async def update_last_sync(session: AsyncSession, user_id: int, timestamp: datetime) -> None:
    """Обновить время последней синхронизации."""
    stmt = update(UserModel).where(UserModel.id == user_id).values(last_sync=timestamp)
    await session.execute(stmt)
    await session.commit()


async def toggle_notifications(session: AsyncSession, user_id: int, enabled: bool) -> None:
    """Включить/выключить уведомления."""
    stmt = update(UserModel).where(UserModel.id == user_id).values(notifications_enabled=enabled)
    await session.execute(stmt)
    await session.commit()
