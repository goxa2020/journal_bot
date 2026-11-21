"""`/logout`: токен, креды и флаг авторизации (задача 2.10)."""

from __future__ import annotations
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.message.auth import logout_handler
from bot.integrations.models import EduUser, TokenInfo
from bot.services.auth import load_token, save_token
from bot.services.users import logout_user

if TYPE_CHECKING:
    import pytest


class RecordingSession:
    """Сессия-заглушка: запоминает UPDATE-выражения и коммиты."""

    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)

    async def commit(self) -> None:
        self.commits += 1


def _values(statement: Any) -> dict[str, Any]:
    return {str(column): parameter.value for column, parameter in statement._values.items()}  # noqa: SLF001


async def test_logout_clears_credentials_and_flag(fake_redis) -> None:
    session = RecordingSession()

    await logout_user(session, 1)  # type: ignore[arg-type]

    assert session.commits == 2
    assert len(session.statements) == 2

    credentials = _values(session.statements[0])
    assert credentials["users.edu_login_encrypted"] is None
    assert credentials["users.edu_password_encrypted"] is None

    flag = _values(session.statements[1])
    assert flag["users.is_authenticated"] is False


async def test_logout_handler_removes_token_and_shows_menu(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
    ru_locale,
) -> None:
    user = EduUser(user_id=1001, group_id=3273, group_name="584 ис-3", fio="Студентов С.С.")
    await save_token(fake_redis, 1, TokenInfo(access_token="token", expires_in_minutes=10080), user)
    assert await load_token(fake_redis, 1) is not None

    message = MagicMock()
    message.from_user.id = 1
    message.answer = AsyncMock()

    db_logout = AsyncMock()
    monkeypatch.setattr("bot.handlers.message.auth.redis_client", fake_redis)
    monkeypatch.setattr("bot.handlers.message.auth.logout_user", db_logout)
    monkeypatch.setattr("bot.handlers.message.auth.get_main_menu_keyboard", AsyncMock(return_value=None))
    monkeypatch.setattr("bot.handlers.message.auth.get_main_menu", AsyncMock(return_value="меню"))

    await logout_handler(message, AsyncMock())

    assert await load_token(fake_redis, 1) is None
    db_logout.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert "вышли" in message.answer.await_args.args[0].lower()
