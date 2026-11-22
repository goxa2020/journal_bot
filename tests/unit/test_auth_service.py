from __future__ import annotations
from typing import Any, Self
from unittest.mock import AsyncMock

import aiohttp
import pytest

from bot.core.errors import EduAuthError, EduUnavailableError
from bot.integrations.edu_tpi import AUTH_URL, FP_URL, EduTpiClient
from bot.services.auth import authenticate_user, handle_auth_login, handle_auth_password, token_key

TOKEN_PAYLOAD = {
    "data": {"accessToken": "token-123", "expiresIn": 10080.0, "id": -22069},
    "state": 1,
}
USER_PAYLOAD = {
    "data": {
        "user": {"userID": -22069, "groupID": 3273, "group": "584 ис-3", "fio": "Максимов Г.К."},
    },
    "state": 1,
}
FINGERPRINT_PAYLOAD = {"data": {"randomIdentity": "fp-1"}, "state": 1}


class _FakeResponse:
    """Минимальный ответ aiohttp: статус, json и заголовки."""

    def __init__(self, status: int = 200, payload: Any = None, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    @property
    def ok(self) -> bool:
        return self.status < 400

    async def json(self, **_kwargs: Any) -> Any:
        return self._payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    """Подменяет `aiohttp.ClientSession`: маршруты по (метод, url)."""

    def __init__(self, routes: dict[tuple[str, str], _FakeResponse | Exception]) -> None:
        self._routes = routes

    async def close(self) -> None:
        return None

    def request(self, method: str, url: str, **_kwargs: Any) -> _FakeResponse:
        route = self._routes.get((method, str(url)))
        if route is None:
            msg = f"unexpected request: {method} {url}"
            raise AssertionError(msg)
        if isinstance(route, Exception):
            raise route
        return route


def _install(monkeypatch: pytest.MonkeyPatch, routes: dict[tuple[str, str], _FakeResponse | Exception]) -> None:
    """Подменить HTTP-слой edu-tpi: сеть в тестах запрещена, стаб свой."""
    monkeypatch.setattr(
        "bot.integrations.edu_tpi.aiohttp.ClientSession",
        lambda **_kwargs: _FakeSession(routes),
    )


async def test_authenticate_user_with_invalid_credentials_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            ("GET", FP_URL): _FakeResponse(payload=FINGERPRINT_PAYLOAD),
            ("POST", AUTH_URL): _FakeResponse(status=401, payload={"state": 0}),
        },
    )

    assert await authenticate_user("student@donstu.ru", "wrong") is None


async def test_authenticate_user_with_server_error_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            ("GET", FP_URL): _FakeResponse(payload=FINGERPRINT_PAYLOAD),
            ("POST", AUTH_URL): _FakeResponse(status=503),
        },
    )

    with pytest.raises(EduUnavailableError):
        await authenticate_user("student@donstu.ru", "secret")


async def test_authenticate_user_with_network_error_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {("GET", FP_URL): aiohttp.ClientConnectionError("connection refused")})

    with pytest.raises(EduUnavailableError):
        await authenticate_user("student@donstu.ru", "secret")


async def test_authenticate_user_with_valid_credentials_returns_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            ("GET", FP_URL): _FakeResponse(payload=FINGERPRINT_PAYLOAD),
            ("POST", AUTH_URL): _FakeResponse(payload=TOKEN_PAYLOAD),
        },
    )

    token = await authenticate_user("student@donstu.ru", "secret")

    assert token is not None
    assert token.access_token == "token-123"
    assert token.expires_in_minutes == 10080.0
    assert token.edu_user_id == -22069


async def test_client_raises_auth_error_on_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            ("GET", FP_URL): _FakeResponse(payload=FINGERPRINT_PAYLOAD),
            ("POST", AUTH_URL): _FakeResponse(status=403),
        },
    )

    async with EduTpiClient() as client:
        with pytest.raises(EduAuthError):
            await client.authorize("student@donstu.ru", "secret")


async def test_handle_auth_login_accepts_valid_email() -> None:
    state_data, success = await handle_auth_login("  student@donstu.ru ", {})

    assert success is True
    assert state_data["login"] == "student@donstu.ru"


@pytest.mark.parametrize("text", [None, "", "no-at-sign", "student@donstu", "@donstu.ru", "a@b@c.ru"])
async def test_handle_auth_login_rejects_invalid_email(text: str | None) -> None:
    state_data, success = await handle_auth_login(text, {})

    assert success is False
    assert "login" not in state_data


async def test_handle_auth_password_stores_token_with_correct_ttl(
    fake_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_credentials = AsyncMock()
    set_data = AsyncMock()
    monkeypatch.setattr("bot.services.auth.set_edu_credentials", set_credentials)
    monkeypatch.setattr("bot.services.auth.set_user_data", set_data)
    _install(
        monkeypatch,
        {
            ("GET", FP_URL): _FakeResponse(payload=FINGERPRINT_PAYLOAD),
            ("POST", AUTH_URL): _FakeResponse(payload=TOKEN_PAYLOAD),
            ("GET", AUTH_URL): _FakeResponse(payload=USER_PAYLOAD),
        },
    )

    success, user = await handle_auth_password(
        user_id=1,
        login="student@donstu.ru",
        password="secret",
        session=AsyncMock(),
    )

    assert success is True
    assert user is not None
    assert user.user_id == -22069

    # expiresIn приходит в минутах: 10080 * 60 − 300 секунд запаса
    key = token_key(1)
    assert await fake_redis.ttl(key) == 604500
    token_payload = await fake_redis.get(key)
    assert token_payload is not None
    assert b"token-123" in token_payload

    set_credentials.assert_awaited_once()
    set_data.assert_awaited_once()


async def test_handle_auth_password_returns_failure_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            ("GET", FP_URL): _FakeResponse(payload=FINGERPRINT_PAYLOAD),
            ("POST", AUTH_URL): _FakeResponse(payload={"data": {"expiresIn": 10080}}),
        },
    )

    success, user = await handle_auth_password(
        user_id=1,
        login="student@donstu.ru",
        password="secret",
        session=AsyncMock(),
    )

    assert success is False
    assert user is None


async def test_handle_auth_password_propagates_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {("GET", FP_URL): _FakeResponse(status=503)})

    with pytest.raises(EduUnavailableError):
        await handle_auth_password(
            user_id=1,
            login="student@donstu.ru",
            password="secret",
            session=AsyncMock(),
        )
