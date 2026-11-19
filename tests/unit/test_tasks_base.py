"""Задачи 1.3 и 1.4: мост sync/async, ресурсы задачи, lock, ретраи и метрики.

Тесты не ходят в сеть, Redis, PostgreSQL и Telegram: движок создаётся, но не
подключается (`NullPool`), Redis подменяется `fakeredis`, задачи выполняются в
`task_always_eager`.
"""

from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import prometheus_client
import pytest
from celery.exceptions import Retry
from sqlalchemy.pool import NullPool

from bot.celery_app import celery_app
from bot.core.errors import PermanentError, RetryableError
from bot.tasks import base
from bot.tasks.base import BaseTask, run_async, task_lock, task_redis, task_session


async def _answer() -> int:
    return 42


def test_run_async_returns_result() -> None:
    assert run_async(_answer()) == 42


async def test_run_async_inside_running_loop_raises() -> None:
    coro = _answer()
    with pytest.raises(RuntimeError, match="event loop"):
        run_async(coro)


async def test_create_task_engine_uses_null_pool() -> None:
    engine = base.create_task_engine()
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        await engine.dispose()


async def test_task_session_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    session = object()

    class _SessionContext:
        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(base, "create_task_engine", lambda: engine)
    monkeypatch.setattr(base, "get_sessionmaker", lambda _engine: _SessionContext)

    async with task_session() as yielded:
        assert yielded is session

    engine.dispose.assert_awaited_once()


async def test_task_redis_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.aclose = AsyncMock()
    monkeypatch.setattr(base, "create_task_redis", lambda: client)

    async with task_redis() as yielded:
        assert yielded is client

    client.aclose.assert_awaited_once()


async def test_task_lock_acquires_free_key(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr(base, "create_task_redis", lambda: client)

    async with task_lock("sync:lock:1", ttl=120) as acquired:
        assert acquired is True
        assert await client.get("sync:lock:1") is not None
        ttl = await client.ttl("sync:lock:1")
        assert 0 < ttl <= 120


async def test_task_lock_skips_busy_key(monkeypatch: pytest.MonkeyPatch, log_messages: list[str]) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    await client.set("sync:lock:2", "1", ex=120)
    monkeypatch.setattr(base, "create_task_redis", lambda: client)

    async with task_lock("sync:lock:2") as acquired:
        assert acquired is False

    assert any("skipped: locked" in message for message in log_messages)


# --- BaseTask: ретраи, логи, метрики ------------------------------------------------


@celery_app.task(base=BaseTask, bind=True, name="tests.unit.retryable")
def _retryable(self: BaseTask) -> None:
    msg = "edu-tpi недоступен"
    raise RetryableError(msg)


@celery_app.task(base=BaseTask, bind=True, name="tests.unit.permanent")
def _permanent(self: BaseTask) -> None:
    msg = "схема ответа изменилась"
    raise PermanentError(msg)


@celery_app.task(base=BaseTask, bind=True, name="tests.unit.locked")
def _locked(self: BaseTask, key: str) -> str:
    return run_async(_locked_work(key))


async def _locked_work(key: str) -> str:
    async with task_lock(key) as acquired:
        if not acquired:
            return "skipped"
        return "done"


def _fake_retry(retry_calls: list[BaseException | None]) -> Any:
    def _retry(*, exc: BaseException | None = None, **_kwargs: Any) -> None:
        retry_calls.append(exc)
        msg = "тестовый повтор"
        raise Retry(msg, exc=exc)

    return _retry


def test_retryable_error_calls_retry(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    retry_calls: list[BaseException | None] = []
    monkeypatch.setattr(_retryable, "retry", _fake_retry(retry_calls))

    with pytest.raises(Retry):
        _retryable.apply()

    assert len(retry_calls) == 1
    assert isinstance(retry_calls[0], RetryableError)


def test_permanent_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
    log_messages: list[str],
) -> None:
    retry = MagicMock()
    monkeypatch.setattr(_permanent, "retry", retry)

    result = _permanent.apply(throw=False)

    retry.assert_not_called()
    assert result.state == "FAILURE"
    assert any("permanent error" in message for message in log_messages)


def test_busy_lock_skips_task_without_error(
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
    log_messages: list[str],
) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    run_async(client.set("sync:lock:7", "1", ex=120))
    monkeypatch.setattr(base, "create_task_redis", lambda: client)

    result = _locked.apply(args=("sync:lock:7",))

    assert result.get() == "skipped"
    assert any("skipped: locked" in message for message in log_messages)


def test_free_lock_runs_task(monkeypatch: pytest.MonkeyPatch, celery_eager) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr(base, "create_task_redis", lambda: client)

    result = _locked.apply(args=("sync:lock:8",))

    assert result.get() == "done"


def test_task_metrics_are_exported(celery_eager) -> None:
    from bot.tasks.service import ping  # noqa: PLC0415 — регистрирует задачу

    ping.apply()

    value = prometheus_client.REGISTRY.get_sample_value(
        "celery_tasks_total",
        {"task": "bot.tasks.service.ping", "status": "success"},
    )
    assert value is not None
    assert value >= 1
    assert prometheus_client.REGISTRY.get_sample_value(
        "celery_task_duration_seconds_count",
        {"task": "bot.tasks.service.ping"},
    )
