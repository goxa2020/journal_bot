"""Режим ожидания: включение, продление, истечение и индекс (задача 5.1/5.3)."""

from __future__ import annotations
import datetime as dt
from typing import Any

import pytest

from bot.services.watch import (
    REASON_NOT_AUTHENTICATED,
    REASON_NOT_FOUND,
    WATCH_USERS_KEY,
    WatchModeService,
)

#: Наивное время, как в `users.watch_mode_expires_at` (TIMESTAMP без tz, московское).
NOW = dt.datetime(2026, 11, 27, 12, 0, 0)  # noqa: DTZ001


class _Result:
    """Минимальный результат `execute`: скаляр или строки — что попросит сервис."""

    def __init__(self, *, scalar: Any = None, rows: list[Any] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalar_one(self) -> Any:
        return self._scalar

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    """Сессия, отдающая заранее заданные результаты по порядку вызовов."""

    def __init__(self, *results: _Result) -> None:
        self._results = list(results)
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        if not self._results:
            message = "лишний execute: сценарий теста не предполагал этот запрос"
            raise AssertionError(message)
        return self._results.pop(0)

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Фиксированное «сейчас»: сроки и остаток считаются от него."""
    monkeypatch.setattr("bot.services.watch.now", lambda: NOW)


def _service(session: _Session, redis: Any, *, minutes: int = 30) -> WatchModeService:
    return WatchModeService(session=session, redis=redis, minutes=minutes)  # type: ignore[arg-type]


async def test_enable_sets_expiry_and_adds_to_index(fake_redis) -> None:
    session = _Session(_Result(scalar=True), _Result())
    service = _service(session, fake_redis)

    outcome = await service.enable(1)

    assert outcome.changed is True
    assert outcome.reason is None
    assert outcome.state.active is True
    assert outcome.state.expires_at == NOW + dt.timedelta(minutes=30)
    assert outcome.state.minutes_left == 30
    assert await fake_redis.smembers(WATCH_USERS_KEY) == {b"1"}
    assert session.commits == 1
    params = session.statements[1].compile().params
    assert params["watch_mode_expires_at"] == NOW + dt.timedelta(minutes=30)


async def test_enable_without_login_changes_nothing(fake_redis) -> None:
    session = _Session(_Result(scalar=False))
    service = _service(session, fake_redis)

    outcome = await service.enable(1)

    assert outcome.changed is False
    assert outcome.reason == REASON_NOT_AUTHENTICATED
    assert outcome.state.active is False
    assert await fake_redis.smembers(WATCH_USERS_KEY) == set()
    assert session.commits == 0


async def test_enable_for_unknown_user_reports_not_found(fake_redis) -> None:
    session = _Session(_Result(scalar=None))
    service = _service(session, fake_redis)

    outcome = await service.enable(999)

    assert outcome.changed is False
    assert outcome.reason == REASON_NOT_FOUND
    assert session.commits == 0


async def test_extend_gives_new_period_from_now(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    """Продление — это новый срок от текущего момента, а не накопление остатка."""
    first = await _service(_Session(_Result(scalar=True), _Result()), fake_redis).enable(1)
    assert first.state.expires_at == NOW + dt.timedelta(minutes=30)

    later = NOW + dt.timedelta(minutes=20)
    monkeypatch.setattr("bot.services.watch.now", lambda: later)

    second = await _service(_Session(_Result(scalar=True), _Result()), fake_redis).enable(1)

    assert second.state.expires_at == later + dt.timedelta(minutes=30)
    assert second.state.minutes_left == 30
    assert await fake_redis.scard(WATCH_USERS_KEY) == 1


async def test_state_reports_rounded_up_minutes(fake_redis) -> None:
    session = _Session(_Result(scalar=NOW + dt.timedelta(minutes=29, seconds=30)))
    service = _service(session, fake_redis)

    state = await service.get_state(1)

    assert state.active is True
    assert state.minutes_left == 30


async def test_state_of_expired_mode_is_inactive(fake_redis) -> None:
    session = _Session(_Result(scalar=NOW - dt.timedelta(minutes=1)))
    service = _service(session, fake_redis)

    state = await service.get_state(1)

    assert state.active is False
    assert state.minutes_left == 0


async def test_state_without_expiry_is_inactive(fake_redis) -> None:
    session = _Session(_Result(scalar=None))
    service = _service(session, fake_redis)

    assert (await service.get_state(1)).active is False


async def test_disable_clears_expiry_and_index(fake_redis) -> None:
    await fake_redis.sadd(WATCH_USERS_KEY, 1)
    session = _Session(_Result())
    service = _service(session, fake_redis)

    outcome = await service.disable(1)

    assert outcome.changed is True
    assert outcome.state.active is False
    assert await fake_redis.smembers(WATCH_USERS_KEY) == set()
    assert session.commits == 1


async def test_expire_stale_clears_expired_and_reconciles_index(fake_redis) -> None:
    """Истёкший снимается, лишний в индексе убирается, активный добавляется."""
    await fake_redis.sadd(WATCH_USERS_KEY, 2, 3)
    session = _Session(_Result(rows=[(2,)]), _Result(), _Result(rows=[(1,)]))
    service = _service(session, fake_redis)

    cleaned = await service.expire_stale()

    assert cleaned == 1
    assert await fake_redis.smembers(WATCH_USERS_KEY) == {b"1"}
    assert session.commits == 1


async def test_expire_stale_is_idempotent(fake_redis) -> None:
    await fake_redis.sadd(WATCH_USERS_KEY, 1)
    session = _Session(_Result(rows=[]), _Result(rows=[(1,)]))
    service = _service(session, fake_redis)

    cleaned = await service.expire_stale()

    assert cleaned == 0
    assert session.commits == 0
    assert await fake_redis.smembers(WATCH_USERS_KEY) == {b"1"}


async def test_active_user_ids_lists_only_waiting_users(fake_redis) -> None:
    session = _Session(_Result(rows=[(1,), (7,)]))
    service = _service(session, fake_redis)

    assert await service.active_user_ids() == [1, 7]
    sql = str(session.statements[0])
    assert "watch_mode_expires_at IS NOT NULL" in sql
    assert "watch_mode_expires_at >" in sql


async def test_count_active_returns_number(fake_redis) -> None:
    session = _Session(_Result(scalar=3))
    service = _service(session, fake_redis)

    assert await service.count_active() == 3


async def test_mark_synced_skips_empty_list(fake_redis) -> None:
    session = _Session()
    service = _service(session, fake_redis)

    await service.mark_synced([])

    assert session.statements == []
    assert session.commits == 0


async def test_mark_synced_writes_last_sync_time(fake_redis) -> None:
    session = _Session(_Result())
    service = _service(session, fake_redis)

    await service.mark_synced([1, 2])

    assert session.commits == 1
    params = session.statements[0].compile().params
    assert params["watch_mode_last_sync_at"] == NOW
