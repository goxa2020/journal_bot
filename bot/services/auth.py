"""Авторизация и токен edu-tpi (docs/ARCHITECTURE.md §7.1, задача 2.4).

Токен живёт в Redis (`auth:token:{user_id}`) и восстанавливается по сохранённым
шифрованным credentials. Все HTTP-вызовы идут через `EduTpiClient`; задач Celery этот
модуль касается только через `TokenService`, который получает Redis и сессию снаружи.
"""

from __future__ import annotations
import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from aiogram.exceptions import TelegramBadRequest

from bot.cache.redis import build_key
from bot.cache.serialization import JSONSerializer
from bot.core.config import TIMEZONE
from bot.core.errors import EduAuthError, EduTokenExpired
from bot.integrations.edu_tpi import EduTpiClient
from bot.services.users import (
    load_edu_credentials,
    mark_authenticated,
    set_edu_credentials,
    set_user_data,
    update_user_identity,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram.types import InlineKeyboardMarkup, Message
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.integrations.models import EduUser, TokenInfo

_T = TypeVar("_T")

# Резервный TTL токена, если API не прислал expiresIn
DEFAULT_TOKEN_TTL_SECONDS = 3600
#: Запас, чтобы не использовать токен в момент истечения.
TOKEN_TTL_MARGIN_SECONDS = 300


@dataclass(frozen=True, slots=True)
class TokenBundle:
    """Значение `auth:token:{user_id}`."""

    token: str
    expires_at: dt.datetime
    edu_user_id: int | None = None
    group_id: int | None = None


def token_ttl_seconds(expires_in: object) -> int:
    """Переводит `expiresIn` (минуты) в секунды для TTL в Redis.

    Держим запас 5 минут, чтобы не использовать токен в момент истечения.
    """
    try:
        minutes = float(str(expires_in))
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_TTL_SECONDS
    return max(int(minutes * 60) - TOKEN_TTL_MARGIN_SECONDS, 60)


def token_key(user_id: int) -> str:
    """Ключ токена: `auth:token:{user_id}` без хвостового двоеточия."""
    return build_key("auth:token", user_id)


async def save_token(
    redis: Redis,
    user_id: int,
    token_info: TokenInfo,
    user: EduUser | None = None,
) -> TokenBundle:
    """Положить токен в Redis с TTL из `expiresIn`."""
    ttl_seconds = token_ttl_seconds(token_info.expires_in_minutes)
    bundle = TokenBundle(
        token=token_info.access_token,
        expires_at=dt.datetime.now(TIMEZONE) + dt.timedelta(seconds=ttl_seconds),
        edu_user_id=user.user_id if user else token_info.edu_user_id,
        group_id=user.group_id if user else None,
    )
    payload = JSONSerializer.serialize(
        {
            "token": bundle.token,
            "expires_at": bundle.expires_at,
            "edu_user_id": bundle.edu_user_id,
            "group_id": bundle.group_id,
        },
    )
    await redis.set(token_key(user_id), payload, ex=ttl_seconds)
    return bundle


async def load_token(redis: Redis, user_id: int) -> TokenBundle | None:
    """Прочитать токен; `None`, если его нет, он истёк или повреждён."""
    raw = await redis.get(token_key(user_id))
    if raw is None:
        return None
    try:
        data = JSONSerializer.deserialize(raw)
        expires_at = data["expires_at"]
        if isinstance(expires_at, str):
            expires_at = dt.datetime.fromisoformat(expires_at)
        token = str(data["token"])
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(expires_at, dt.datetime) or expires_at <= dt.datetime.now(TIMEZONE):
        return None
    return TokenBundle(
        token=token,
        expires_at=expires_at,
        edu_user_id=data.get("edu_user_id"),
        group_id=data.get("group_id"),
    )


async def delete_token(redis: Redis, user_id: int) -> None:
    """Удалить токен (выход или 401 после переавторизации)."""
    await redis.delete(token_key(user_id))


class TokenService:
    """Токен пользователя: кеш, переавторизация и повтор после 401.

    Один экземпляр — одна задача синхронизации: `call()` сам повторяет операцию один
    раз после переавторизации, второй 401 означает, что сохранённые данные не годятся.
    """

    def __init__(
        self,
        *,
        redis: Redis,
        session: AsyncSession,
        user_id: int,
        client: EduTpiClient,
    ) -> None:
        self._redis = redis
        self._session = session
        self._user_id = user_id
        self._client = client
        self._bundle: TokenBundle | None = None

    async def get(self) -> str:
        """Токен из Redis; при промахе — авторизация по сохранённым данным."""
        if self._bundle is not None:
            return self._bundle.token
        bundle = await load_token(self._redis, self._user_id)
        if bundle is None:
            bundle = await self.reauthorize()
        self._bundle = bundle
        return bundle.token

    async def reauthorize(self) -> TokenBundle:
        """Сбросить токен и войти заново по сохранённым credentials."""
        login, password = await load_edu_credentials(self._session, self._user_id)
        if not login or not password:
            await mark_authenticated(self._session, self._user_id, value=False)
            message = "Нет сохранённых учётных данных edu-tpi"
            raise EduAuthError(message)

        try:
            token_info = await self._client.authorize(login, password)
            user = await self._client.get_user_info(token_info.access_token)
        except EduAuthError:
            await delete_token(self._redis, self._user_id)
            await mark_authenticated(self._session, self._user_id, value=False)
            raise
        except EduTokenExpired as exc:
            await delete_token(self._redis, self._user_id)
            await mark_authenticated(self._session, self._user_id, value=False)
            message = "Свежий токен edu-tpi отклонён"
            raise EduAuthError(message) from exc

        bundle = await save_token(self._redis, self._user_id, token_info, user)
        await update_user_identity(
            self._session,
            self._user_id,
            edu_user_id=user.user_id,
            group_id=user.group_id,
            group_name=user.group_name,
            full_name=user.fio or user.full_name,
        )
        self._bundle = bundle
        return bundle

    async def call(self, operation: Callable[[str], Awaitable[_T]]) -> _T:
        """Выполнить вызов с токеном; 401 — одна переавторизация и один повтор."""
        token = await self.get()
        try:
            return await operation(token)
        except EduTokenExpired:
            await delete_token(self._redis, self._user_id)
            self._bundle = None
            token = await self.get()
            try:
                return await operation(token)
            except EduTokenExpired as exc:
                await delete_token(self._redis, self._user_id)
                await mark_authenticated(self._session, self._user_id, value=False)
                message = "Токен edu-tpi отклонён после переавторизации"
                raise EduAuthError(message) from exc


async def authenticate_user(username: str, password: str) -> TokenInfo | None:
    """Авторизация пользователя с его edu credentials.

    Возвращает `TokenInfo`; `None` — неверные учётные данные; сбой сети или сервиса
    пробрасывается как `EduUnavailableError` из клиента.
    """
    async with EduTpiClient() as client:
        try:
            return await client.authorize(username, password)
        except EduAuthError:
            return None


async def edit_bot_message(
    message: Message,
    bot_message_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int:
    """Редактирует сообщение бота или отправляет новое.
    Возвращает ID сообщения бота.
    """
    if bot_message_id and message.bot:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exc:
            # Тот же текст и та же клавиатура — редактировать нечего, это не ошибка
            if "message is not modified" in str(exc):
                return bot_message_id
            # Иначе сообщение удалено или слишком старое — отправим новое
        else:
            return bot_message_id

    sent = await message.answer(text, reply_markup=reply_markup)
    return sent.message_id


async def handle_auth_login(
    text: str | None,
    state_data: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Обрабатывает ввод логина.
    Возвращает (новые данные состояния, успех).
    """
    if not text:
        return state_data, False

    login = text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", login):
        return state_data, False

    state_data["login"] = login
    return state_data, True


async def handle_auth_password(
    user_id: int,
    login: str,
    password: str,
    session: AsyncSession,
) -> tuple[bool, EduUser | None]:
    """Выполняет авторизацию и сохраняет данные.
    Возвращает (успех, данные пользователя).
    """
    if not password:
        return False, None

    async with EduTpiClient() as client:
        try:
            token_info = await client.authorize(login, password)
        except EduAuthError:
            return False, None

        try:
            user = await client.get_user_info(token_info.access_token)
        except (EduAuthError, EduTokenExpired):
            return False, None

        # Токен пишется в Redis-клиент процесса бота: это обработчик входа, а не
        # Celery-задача, поэтому глобальный клиент здесь допустим.
        from bot.core.loader import redis_client  # noqa: PLC0415

        await save_token(redis_client, user_id, token_info, user)

    await set_edu_credentials(session, user_id, login, password)
    await set_user_data(
        session=session,
        user_id=user_id,
        edu_user_id=user.user_id,
        group_id=user.group_id,
        group_name=user.group_name,
        full_name=user.fio or user.full_name,
        is_authenticated=True,
    )
    return True, user
