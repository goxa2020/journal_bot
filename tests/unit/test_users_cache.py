from __future__ import annotations
from unittest.mock import AsyncMock

from bot.cache.redis import build_key, cached, clear_cache
from bot.services import users

_PROBE_CALLS = {"count": 0}


class _Result:
    def __init__(self, *, value: bool) -> None:
        self._value = value

    def scalar_one_or_none(self) -> bool:
        return self._value


class _Session:
    def __init__(self, *, authorized: bool = True) -> None:
        self.execute = AsyncMock(return_value=_Result(value=authorized))
        self.commit = AsyncMock()


@cached(key_builder=lambda _session, user_id: build_key(user_id))
async def _probe(_session, user_id: int) -> int:
    _PROBE_CALLS["count"] += 1
    return user_id * 2


async def test_is_authorized_hits_database_once(fake_redis) -> None:
    session = _Session(authorized=True)

    assert await users.is_authorized(session, 1) is True
    assert await users.is_authorized(session, 1) is True

    assert session.execute.await_count == 1


async def test_set_user_data_invalidates_is_authorized(fake_redis) -> None:
    session = _Session(authorized=True)
    assert await users.is_authorized(session, 1) is True
    assert await fake_redis.keys("*")

    await users.set_user_data(session, 1, full_name="Иванов И.И.", is_authenticated=False)
    assert await fake_redis.keys("*") == []

    session.execute.return_value = _Result(value=False)
    assert await users.is_authorized(session, 1) is False
    # запрос is_authorized, update в set_user_data, повторный запрос после сброса
    assert session.execute.await_count == 3


async def test_clear_cache_deletes_the_key_that_cached_uses(fake_redis) -> None:
    _PROBE_CALLS["count"] = 0

    assert await _probe(None, 5) == 10
    assert await _probe(None, 5) == 10
    assert _PROBE_CALLS["count"] == 1
    assert await fake_redis.keys("*")

    await clear_cache(_probe, 5)
    assert await fake_redis.keys("*") == []

    assert await _probe(None, 5) == 10
    assert _PROBE_CALLS["count"] == 2
