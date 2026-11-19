from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update

from bot.cache.redis import build_key, cached, clear_cache
from bot.core.encryption import decrypt, encrypt
from bot.database.models import User

if TYPE_CHECKING:
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
    await clear_cache(get_user_count)
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
    await clear_cache(get_language_code, user_id)


async def set_user_data(  # noqa: PLR0913, PLR0917
    session: AsyncSession,
    user_id: int,
    edu_user_id: str | None = None,
    group_id: int | None = None,
    group_name: str | None = None,
    full_name: str | None = None,
    is_authenticated: bool | None = None,
) -> None:
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(
            edu_user_id=edu_user_id,
            group_id=group_id,
            group_name=group_name,
            full_name=full_name,
            is_authenticated=is_authenticated,
        )
    )

    await session.execute(stmt)
    await session.commit()
    await clear_cache(is_authorized, user_id)
    await clear_cache(get_full_name, user_id)


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def is_admin(session: AsyncSession, user_id: int) -> bool:
    query = select(User.is_admin).filter_by(id=user_id)

    result = await session.execute(query)

    is_admin = result.scalar_one_or_none()
    return bool(is_admin)


async def set_is_admin(session: AsyncSession, user_id: int, value: bool) -> None:
    stmt = update(User).where(User.id == user_id).values(is_admin=value)

    await session.execute(stmt)
    await session.commit()
    await clear_cache(is_admin, user_id)
    await clear_cache(get_admins_ids)


# Кеш не нужен: функция вызывается только в админском экспорте, а ORM-объекты
# в pickle — это detached-инстансы, которые ломаются при первом обращении к
# relationship вне сессии. Список id (`get_admins_ids`) кешировать безопасно.
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

    # decrypt() логирует warning и возвращает None, если ключ сменился или токен повреждён
    return decrypt(row[0]), decrypt(row[1])


async def set_edu_credentials(session: AsyncSession, user_id: int, username: str, password: str) -> None:
    """Сохранить зашифрованные edu credentials пользователя."""
    username_encrypted = encrypt(username)
    password_encrypted = encrypt(password)

    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(edu_login_encrypted=username_encrypted, edu_password_encrypted=password_encrypted)
    )
    await session.execute(stmt)
    await session.commit()
    await clear_cache(get_edu_credentials, user_id)


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def is_authorized(session: AsyncSession, user_id: int) -> bool:
    """Проверить, авторизован ли пользователь.

    Проверка идёт на каждом апдейте, поэтому результат кешируется на 10 секунд;
    `set_user_data` сбрасывает кеш сразу после изменения `is_authenticated`.
    """
    query = select(User.is_authenticated).filter_by(id=user_id)

    result = await session.execute(query)

    is_authenticated = result.scalar_one_or_none()
    return bool(is_authenticated)
