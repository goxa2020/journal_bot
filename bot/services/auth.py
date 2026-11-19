import re
from datetime import datetime, timedelta
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message
from aiohttp import ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.cache.redis import build_key, set_redis_value
from bot.cache.serialization import JSONSerializer
from bot.core.config import TIMEZONE
from bot.services.api_client import (
    EduUnavailableError,
    InvalidCredsError,
    ParseError,
    auth_post,
    get_auth_data,
    get_fingerprint,
)
from bot.services.users import set_edu_credentials, set_user_data

# Резервный TTL токена, если API не прислал expiresIn
DEFAULT_TOKEN_TTL_SECONDS = 3600


def token_ttl_seconds(expires_in: object) -> int:
    """Переводит `expiresIn` (минуты) в секунды для TTL в Redis.

    Держим запас 5 минут, чтобы не использовать токен в момент истечения.
    """
    try:
        minutes = float(str(expires_in))
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_TTL_SECONDS
    return max(int(minutes * 60) - 300, 60)


async def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    """Авторизация пользователя с его edu credentials.

    Возвращает `data` из ответа API: accessToken, expiresIn (минуты), id.
    `None` — неверные учётные данные; сбой сети или сервиса — `EduUnavailableError`.
    """
    try:
        fingerprint = await get_fingerprint()
        auth_data = await auth_post(username, password, fingerprint)
    except InvalidCredsError:
        return None
    except (ClientError, TimeoutError, ParseError) as exc:
        msg = "edu-tpi недоступен"
        raise EduUnavailableError(msg) from exc
    return dict(auth_data)


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
) -> tuple[bool, dict[str, Any] | None]:
    """Выполняет авторизацию и сохраняет данные.
    Возвращает (успех, данные пользователя).
    """
    if not password:
        return False, None

    try:
        auth_post_resp = await authenticate_user(login, password)
        if not auth_post_resp:
            return False, None

        # Ключ в ответе API — accessToken (camelCase), а не access_token
        access_token = auth_post_resp.get("accessToken")
        if not isinstance(access_token, str) or not access_token:
            return False, None

        auth_data = await get_auth_data(access_token)
    except (ClientError, TimeoutError, ParseError) as exc:
        msg = "edu-tpi недоступен"
        raise EduUnavailableError(msg) from exc

    user_data_raw = auth_data.get("user")
    if not isinstance(user_data_raw, dict):
        return False, None

    user_data: dict[str, Any] = user_data_raw

    # expiresIn приходит в минутах, в Redis храним секунды
    ttl_seconds = token_ttl_seconds(auth_post_resp.get("expiresIn"))

    cache_data = JSONSerializer.serialize(
        {
            "token": access_token,
            "expires_at": datetime.now(TIMEZONE) + timedelta(seconds=ttl_seconds),
            "edu_user_id": user_data.get("userID"),
            "group_id": user_data.get("groupID"),
        }
    )
    await set_redis_value(build_key("auth:token", user_id), cache_data, ttl_seconds)

    await set_edu_credentials(session, user_id, login, password)
    await set_user_data(
        session=session,
        user_id=user_id,
        edu_user_id=user_data.get("userID"),
        group_id=user_data.get("groupID"),
        group_name=user_data.get("group"),
        full_name=user_data.get("fio"),
        is_authenticated=True,
    )

    return True, user_data
