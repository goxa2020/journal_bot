from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select, update

from bot.cache.redis import build_key, cached, clear_cache
from bot.core.config import settings
from bot.database.models import User

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from datetime import datetime

    from aiogram.types import User as tg_User
    from sqlalchemy.ext.asyncio import AsyncSession


async def add_user(
    session: AsyncSession,
    user: tg_User,
) -> User:
    """Add a new user to the database."""

    new_user = User(
        id=user.id,
        language_code=user.language_code,
    )

    session.add(new_user)
    await session.commit()
    await clear_cache(user_exists, user.id)
    return new_user


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def user_exists(session: AsyncSession, user_id: int) -> bool:
    """Checks if the user is in the database."""
    query = select(User.id).filter_by(id=user_id).limit(1)

    result = await session.execute(query)

    user = result.scalar_one_or_none()
    return bool(user)


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def get_full_name(session: AsyncSession, user_id: int) -> str:
    query = select(User.full_name).filter_by(id=user_id)

    result = await session.execute(query)

    full_name = result.scalar_one_or_none()
    return full_name or ""


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def get_language_code(session: AsyncSession, user_id: int) -> str:
    query = select(User.language_code).filter_by(id=user_id)

    result = await session.execute(query)

    language_code = result.scalar_one_or_none()
    return language_code or ""


async def set_language_code(
    session: AsyncSession,
    user_id: int,
    language_code: str,
) -> None:
    stmt = update(User).where(User.id == user_id).values(language_code=language_code)

    await session.execute(stmt)
    await session.commit()


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def is_admin(session: AsyncSession, user_id: int) -> bool:
    query = select(User.is_admin).filter_by(id=user_id)

    result = await session.execute(query)

    is_admin = result.scalar_one_or_none()
    return bool(is_admin)


async def set_is_admin(session: AsyncSession, user_id: int, is_admin: bool) -> None:
    stmt = update(User).where(User.id == user_id).values(is_admin=is_admin)

    await session.execute(stmt)
    await session.commit()


@cached(key_builder=lambda session: build_key())
async def get_all_users(session: AsyncSession) -> list[User]:
    query = select(User)

    result = await session.execute(query)

    users = result.scalars()
    return list(users)


@cached(key_builder=lambda session: build_key())
async def get_admins_ids(session: AsyncSession) -> list[int]:
    query = select(User.id).filter_by(is_admin=True)

    result = await session.execute(query)

    admin_ids = result.scalars()
    return list(admin_ids)


@cached(key_builder=lambda session: build_key())
async def get_user_count(session: AsyncSession) -> int:
    query = select(func.count()).select_from(User)

    result = await session.execute(query)

    count = result.scalar_one_or_none() or 0
    return int(count)


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def get_edu_credentials(session: AsyncSession, user_id: int) -> tuple[str | None, str | None]:
    """Получить расшифрованные edu credentials пользователя."""
    query = select(User.edu_login_encrypted, User.edu_password_encrypted).filter_by(id=user_id)

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
        update(User)
        .where(User.id == user_id)
        .values(edu_login_encrypted=username_encrypted, edu_password_encrypted=password_encrypted)
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
    stmt = update(User).where(User.id == user_id).values(last_sync=timestamp)
    await session.execute(stmt)
    await session.commit()


async def toggle_notifications(session: AsyncSession, user_id: int, enabled: bool) -> None:
    """Включить/выключить уведомления."""
    stmt = update(User).where(User.id == user_id).values(notifications_enabled=enabled)
    await session.execute(stmt)
    await session.commit()
