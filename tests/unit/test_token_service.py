"""Кеш токена, переавторизация и обработка 401 (задача 2.4)."""

from __future__ import annotations
import datetime as dt
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from bot.cache.serialization import JSONSerializer
from bot.core.config import TIMEZONE
from bot.core.encryption import encrypt
from bot.core.errors import EduAuthError, EduTokenExpired
from bot.integrations.models import EduUser, TokenInfo
from bot.services.auth import TokenService, load_token, save_token, token_key


class FakeEduClient:
    def __init__(self, *, token: str = "new-token", auth_error: Exception | None = None) -> None:  # noqa: S107
        self.token = token
        self.auth_error = auth_error
        self.authorize_calls = 0
        self.user_info_calls = 0

    async def authorize(self, _login: str, _password: str) -> TokenInfo:
        self.authorize_calls += 1
        if self.auth_error is not None:
            raise self.auth_error
        return TokenInfo(access_token=self.token, expires_in_minutes=10080, edu_user_id=1001)

    async def get_user_info(self, _token: str) -> EduUser:
        self.user_info_calls += 1
        return EduUser(user_id=1001, group_id=3273, group_name="584 ис-3", fio="Студентов С.С.")


USER = EduUser(user_id=1001, group_id=3273, group_name="584 ис-3", fio="Студентов С.С.")


def _patch_db(monkeypatch: pytest.MonkeyPatch, *, credentials: tuple[str | None, str | None]) -> dict[str, AsyncMock]:
    mocks = {
        "load_edu_credentials": AsyncMock(return_value=credentials),
        "update_user_identity": AsyncMock(),
        "mark_authenticated": AsyncMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"bot.services.auth.{name}", mock)
    return mocks


async def test_get_returns_cached_token_without_authorization(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db(monkeypatch, credentials=("login", "pass"))
    client = FakeEduClient()
    await save_token(fake_redis, 1, TokenInfo(access_token="cached", expires_in_minutes=10080), USER)
    session = AsyncMock()
    service = TokenService(redis=fake_redis, session=session, user_id=1, client=client)  # type: ignore[arg-type]

    assert await service.get() == "cached"
    assert client.authorize_calls == 0


async def test_missing_token_reauthorizes_and_stores_it(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_db(monkeypatch, credentials=("login", "pass"))
    client = FakeEduClient(token="fresh")
    session = AsyncMock()
    service = TokenService(redis=fake_redis, session=session, user_id=1, client=client)  # type: ignore[arg-type]

    assert await service.get() == "fresh"
    assert client.authorize_calls == 1
    assert client.user_info_calls == 1
    bundle = await load_token(fake_redis, 1)
    assert bundle is not None
    assert bundle.token == "fresh"
    assert bundle.edu_user_id == 1001
    mocks["update_user_identity"].assert_awaited_once()


async def test_expired_token_is_reauthored(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db(monkeypatch, credentials=("login", "pass"))
    expired = {
        "token": "old",
        "expires_at": dt.datetime.now(TIMEZONE) - dt.timedelta(minutes=1),
        "edu_user_id": 1001,
        "group_id": 3273,
    }
    await fake_redis.set(token_key(1), JSONSerializer.serialize(expired))
    client = FakeEduClient(token="fresh")
    session = AsyncMock()
    service = TokenService(redis=fake_redis, session=session, user_id=1, client=client)  # type: ignore[arg-type]

    assert await service.get() == "fresh"
    assert client.authorize_calls == 1


async def test_call_reauthorizes_once_after_401(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db(monkeypatch, credentials=("login", "pass"))
    client = FakeEduClient(token="fresh")
    await save_token(fake_redis, 1, TokenInfo(access_token="stale", expires_in_minutes=10080), USER)
    session = AsyncMock()
    service = TokenService(redis=fake_redis, session=session, user_id=1, client=client)  # type: ignore[arg-type]

    calls: list[str] = []

    async def operation(token: str) -> str:
        calls.append(token)
        if token == "stale":
            msg = "expired"
            raise EduTokenExpired(msg)
        return "ok"

    assert await service.call(operation) == "ok"
    assert calls == ["stale", "fresh"]
    assert client.authorize_calls == 1


async def test_second_401_marks_user_unauthenticated(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_db(monkeypatch, credentials=("login", "pass"))
    client = FakeEduClient(token="fresh")
    await save_token(fake_redis, 1, TokenInfo(access_token="stale", expires_in_minutes=10080), USER)
    session = AsyncMock()
    service = TokenService(redis=fake_redis, session=session, user_id=1, client=client)  # type: ignore[arg-type]

    async def operation(_token: str) -> str:
        msg = "expired"
        raise EduTokenExpired(msg)

    with pytest.raises(EduAuthError):
        await service.call(operation)

    assert await fake_redis.get(token_key(1)) is None
    mocks["mark_authenticated"].assert_awaited_with(session, 1, value=False)


async def test_reauth_without_saved_credentials_marks_unauthenticated(
    fake_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_db(monkeypatch, credentials=(None, None))
    client = FakeEduClient()
    session = AsyncMock()
    service = TokenService(redis=fake_redis, session=session, user_id=1, client=client)  # type: ignore[arg-type]

    with pytest.raises(EduAuthError):
        await service.get()

    mocks["mark_authenticated"].assert_awaited_once()
    assert client.authorize_calls == 0


async def test_rejected_credentials_mark_unauthenticated(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_db(monkeypatch, credentials=("login", "wrong"))
    client = FakeEduClient(auth_error=EduAuthError("bad credentials"))
    session = AsyncMock()
    service = TokenService(redis=fake_redis, session=session, user_id=1, client=client)  # type: ignore[arg-type]

    with pytest.raises(EduAuthError):
        await service.get()

    mocks["mark_authenticated"].assert_awaited_with(session, 1, value=False)


class CorruptedCredentialSession:
    """Сессия-заглушка: SELECT отдаёт повреждённый Fernet-токен, UPDATE — без результата."""

    def __init__(self, row: tuple[str, str]) -> None:
        self._row = row
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)
        return SimpleNamespace(fetchone=lambda: self._row)

    async def commit(self) -> None:
        self.commits += 1


def _update_values(statement: Any) -> dict[str, Any]:
    return {str(column): parameter.value for column, parameter in statement._values.items()}  # noqa: SLF001


async def test_corrupted_credentials_raise_auth_error_without_leaking_token(
    fake_redis,
    log_messages: list[str],
) -> None:
    """W1.3: повреждённый токен — повторный вход, а не падение и не утечка в лог.

    `load_edu_credentials` возвращает `(None, <пароль>)`: любая повреждённая часть
    делает пару непригодной. `TokenService` переводит это в `EduAuthError`, снимает
    `is_authenticated` и не пишет в лог ни токен, ни пароль.
    """
    encrypted = encrypt("secret-password")
    corrupted = encrypted[:-2] + "AA"
    session = CorruptedCredentialSession((corrupted, encrypted))
    client = FakeEduClient()
    service = TokenService(redis=fake_redis, session=session, user_id=1, client=client)  # type: ignore[arg-type]

    with pytest.raises(EduAuthError):
        await service.get()

    assert client.authorize_calls == 0
    assert await fake_redis.get(token_key(1)) is None
    assert session.commits == 1
    assert _update_values(session.statements[-1])["users.is_authenticated"] is False

    joined = "\n".join(log_messages)
    assert "user_id=1" in joined
    assert corrupted not in joined
    assert encrypted not in joined
    assert "secret-password" not in joined

    from bot.utils.translations import translate  # noqa: PLC0415 — после env конфигурации

    assert "войдите" in translate("ru", "sync.auth_required").lower()
