from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Select, func, select, update

from bot.cache.redis import build_key, cached, clear_cache
from bot.core.encryption import decrypt, encrypt
from bot.database.models import User

if TYPE_CHECKING:
    from aiogram.types import User as tg_User
    from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_MORNING_NOTIFICATION_TIME = dt.time(8, 0)


@dataclass(frozen=True, slots=True)
class UserSyncInfo:
    """Минимум полей пользователя, нужный синхронизации (без ORM-объекта в задаче)."""

    id: int
    is_authenticated: bool
    edu_user_id: int | None
    group_id: int | None
    group_name: str | None
    full_name: str | None
    language_code: str | None


#: Колонки `users`, которые нужны синхронизации (см. `UserSyncInfo`).
SYNC_INFO_COLUMNS = (
    User.id,
    User.is_authenticated,
    User.edu_user_id,
    User.group_id,
    User.group_name,
    User.full_name,
    User.language_code,
)


def _sync_info(row: Any) -> UserSyncInfo:
    """Собрать :class:`UserSyncInfo` из строки выборки `SYNC_INFO_COLUMNS`."""
    return UserSyncInfo(
        id=row[0],
        is_authenticated=bool(row[1]),
        edu_user_id=row[2],
        group_id=row[3],
        group_name=row[4],
        full_name=row[5],
        language_code=row[6],
    )


def _sync_candidates_query() -> Select[Any]:
    """Пользователи, которых вообще можно синхронизировать (без группы — нельзя)."""
    query = (
        select(*SYNC_INFO_COLUMNS)
        .where(
            User.is_authenticated.is_(True),
            User.group_id.is_not(None),
            User.edu_user_id.is_not(None),
        )
        .order_by(User.group_id, User.id)
    )
    return cast("Select[Any]", query)


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    """Настройки уведомлений пользователя (задачи 3.1–3.3), без ORM-объекта."""

    enabled: bool
    morning_enabled: bool
    morning_time: dt.time
    language_code: str | None = None


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
    edu_user_id: int | None = None,
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


async def load_admin_ids(session: AsyncSession) -> list[int]:
    """Telegram id админов — версия без кеша для Celery-задач (задача 4.4).

    `get_admins_ids` кешируется через глобальный Redis процесса бота и из воркера
    недоступна, поэтому алерт админам читает id напрямую из БД.
    """
    query = select(User.id).filter_by(is_admin=True).order_by(User.id)
    return list((await session.execute(query)).scalars())


@cached(key_builder=lambda session: build_key())
async def get_user_count(session: AsyncSession) -> int:
    query = select(func.count()).select_from(User)

    result = await session.execute(query)

    count = result.scalar_one_or_none() or 0
    return int(count)


@cached(key_builder=lambda session, user_id: build_key(user_id))
async def get_edu_credentials(session: AsyncSession, user_id: int) -> tuple[str | None, str | None]:
    """Получить расшифрованные edu credentials пользователя (кеш бота)."""
    return await load_edu_credentials(session, user_id)


async def load_edu_credentials(session: AsyncSession, user_id: int) -> tuple[str | None, str | None]:
    """Прочитать и расшифровать credentials без кеша.

    Версия без `@cached` нужна Celery-задачам: они не имеют права обращаться к
    глобальному Redis-клиенту бота (`bot.core.loader`).
    """
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


async def clear_edu_credentials(session: AsyncSession, user_id: int) -> None:
    """Удалить шифрованные credentials (выход из edu-tpi)."""
    stmt = update(User).where(User.id == user_id).values(edu_login_encrypted=None, edu_password_encrypted=None)
    await session.execute(stmt)
    await session.commit()
    await clear_cache(get_edu_credentials, user_id)


async def mark_authenticated(session: AsyncSession, user_id: int, *, value: bool) -> None:
    """Только флаг `is_authenticated`, без затирания остальных полей.

    Версия без кеша: её использует воркер. Кеш `is_authorized` живёт 10 секунд и
    обновится сам, а в процессе бота после изменения вызывается `set_user_data`.
    """
    stmt = update(User).where(User.id == user_id).values(is_authenticated=value)
    await session.execute(stmt)
    await session.commit()


async def update_user_identity(  # noqa: PLR0913
    session: AsyncSession,
    user_id: int,
    *,
    edu_user_id: int | None,
    group_id: int | None,
    group_name: str | None,
    full_name: str | None,
) -> None:
    """Обновить данные студента после (пере)авторизации; версия для воркера."""
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(
            edu_user_id=edu_user_id,
            group_id=group_id,
            group_name=group_name,
            full_name=full_name,
            is_authenticated=True,
        )
    )
    await session.execute(stmt)
    await session.commit()


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


async def load_user_sync_info(session: AsyncSession, user_id: int) -> UserSyncInfo | None:
    """Данные пользователя для синхронизации — одним запросом и без кеша."""
    query = select(*SYNC_INFO_COLUMNS).filter_by(id=user_id)
    row = (await session.execute(query)).first()
    if row is None:
        return None
    return _sync_info(row)


async def load_sync_candidates(session: AsyncSession) -> list[UserSyncInfo]:
    """Всех, кого можно синхронизировать фоновой задачей, — без кеша.

    Версия без `@cached`, как `load_edu_credentials`: её вызывает Celery-воркер, а
    глобальный Redis-клиент бота (`bot.core.loader`) задачам недоступен. Пользователи
    без группы или `edu_user_id` в выборку не попадают — их нечем синхронизировать.
    """
    rows = (await session.execute(_sync_candidates_query())).all()
    return [_sync_info(row) for row in rows]


async def load_group_members(session: AsyncSession, group_id: int) -> list[UserSyncInfo]:
    """Участники группы, которых можно синхронизировать (задача 4.2), — без кеша."""
    query = _sync_candidates_query().where(User.group_id == group_id).order_by(User.edu_user_id, User.id)
    rows = (await session.execute(query)).all()
    return [_sync_info(row) for row in rows]


async def load_notification_settings(session: AsyncSession, user_id: int) -> NotificationSettings | None:
    """Настройки уведомлений пользователя — одним запросом и без кеша.

    Версия без `@cached`, как `load_edu_credentials`: её читает и воркер, а глобальный
    Redis-клиент бота (`bot.core.loader`) задачам недоступен.
    """
    query = select(
        User.notification_enabled,
        User.morning_notification_enabled,
        User.morning_notification_time,
        User.language_code,
    ).filter_by(id=user_id)

    row = (await session.execute(query)).first()
    if row is None:
        return None
    return NotificationSettings(
        enabled=bool(row[0]),
        morning_enabled=bool(row[1]),
        morning_time=row[2] or DEFAULT_MORNING_NOTIFICATION_TIME,
        language_code=row[3],
    )


async def set_notification_enabled(session: AsyncSession, user_id: int, *, enabled: bool) -> None:
    """Включить/выключить уведомления (экран `/settings` и блокировка бота)."""
    stmt = update(User).where(User.id == user_id).values(notification_enabled=enabled)
    await session.execute(stmt)
    await session.commit()


async def set_morning_notification(
    session: AsyncSession,
    user_id: int,
    *,
    enabled: bool,
    morning_time: dt.time,
) -> None:
    """Ночное накопление: флаг и время утренней сводки."""
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(morning_notification_enabled=enabled, morning_notification_time=morning_time)
    )
    await session.execute(stmt)
    await session.commit()


async def logout_user(session: AsyncSession, user_id: int) -> None:
    """Выход: удалить credentials и снять флаг авторизации.

    Токен в Redis удаляет вызывающий (`bot.services.auth.delete_token`): у процесса
    бота есть Redis-клиент, а у сервиса пользователей нет.
    """
    await clear_edu_credentials(session, user_id)
    await mark_authenticated(session, user_id, value=False)
    await clear_cache(is_authorized, user_id)
    await clear_cache(get_full_name, user_id)
