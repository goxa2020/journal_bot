import json
from http import HTTPStatus
from typing import Any

import aiohttp

from bot.core.config import AUTH_URL, FP_URL

timeout = aiohttp.ClientTimeout(total=60)


class InvalidCredsError(Exception):
    """Ошибка неверных учетных данных."""


class ParseError(Exception):
    """Ошибка парсинга данных журнала."""


class EduUnavailableError(Exception):
    """edu-tpi недоступен: сеть, таймаут или неожиданный ответ."""


async def get_fingerprint() -> str:
    """
    Получение рандомного идентификатора пользователя.
    """
    async with aiohttp.ClientSession(timeout=timeout) as session, session.get(FP_URL) as resp:
        resp.raise_for_status()
        fp_json = await resp.json()
        return str(fp_json["data"]["randomIdentity"])


async def auth_post(username: str, password: str, fingerprint: str) -> dict[str, Any]:
    token_data = {
        "fingerprint": fingerprint,
        "userName": username,
        "password": password,
    }

    async with aiohttp.ClientSession(timeout=timeout) as session, session.post(AUTH_URL, json=token_data) as resp:
        # 400/401/403 — неверная пара логин/пароль; 5xx и 429 — сбой сервиса,
        # его нужно показать как «недоступен», а не как «неверные данные».
        if resp.status in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            msg = f"Auth failed: status {resp.status}"
            raise InvalidCredsError(msg)
        if resp.status >= HTTPStatus.INTERNAL_SERVER_ERROR or resp.status == HTTPStatus.TOO_MANY_REQUESTS:
            msg = f"edu-tpi unavailable: status {resp.status}"
            raise EduUnavailableError(msg)
        resp.raise_for_status()
        try:
            token_json = await resp.json()
        except json.JSONDecodeError as e:
            msg = "Invalid auth response"
            raise InvalidCredsError(msg) from e
        if "data" not in token_json or "accessToken" not in token_json["data"]:
            msg = "No accessToken in auth response"
            raise InvalidCredsError(msg)
        return dict(token_json["data"])


async def get_auth_data(access_token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession(timeout=timeout) as session, session.get(AUTH_URL, headers=headers) as resp:
        resp.raise_for_status()
        try:
            user_data = await resp.json()
        except json.JSONDecodeError as e:
            msg = "Invalid user data response"
            raise ParseError(msg) from e
        return dict(user_data.get("data"))
