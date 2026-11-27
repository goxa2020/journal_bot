"""Служебные задачи: smoke-задача `ping` и уборка истёкших режимов ожидания (фаза 5)."""

from __future__ import annotations
from typing import Any

from bot.celery_app import celery_app
from bot.core.config import settings
from bot.core.metrics import set_active_watch_users
from bot.services.watch import WatchModeService
from bot.tasks.base import BaseTask, run_async, task_redis, task_session


# celery не поставляет типы, поэтому декоратор задачи для mypy нетипизированный.
@celery_app.task(base=BaseTask, bind=True, name="bot.tasks.service.ping")  # type: ignore[untyped-decorator]
def ping(self: BaseTask) -> str:
    """Проверить, что воркер жив и задачи выполняются (очередь `maintenance`).

    Ни БД, ни Telegram, ни Redis: задача для `celery inspect`, ручных проверок и
    smoke-теста в eager-режиме.
    """
    return "pong"


async def _run_watch_cleanup() -> dict[str, Any]:
    """Снять истёкшие режимы и выровнять индекс `watch_mode:users` по БД.

    Идемпотентно: повторный запуск ничего не меняет (задача 5.3, SC-006).
    """
    async with task_redis() as redis, task_session() as session:
        watch = WatchModeService(session=session, redis=redis, minutes=settings.WATCH_MODE_MINUTES)
        cleaned = await watch.expire_stale()
        active = await watch.count_active()
    set_active_watch_users(active)
    return {"cleaned": cleaned, "active": active}


# celery не поставляет типы, поэтому декоратор задачи для mypy нетипизированный.
@celery_app.task(  # type: ignore[untyped-decorator]
    base=BaseTask,
    bind=True,
    name="bot.tasks.service.cleanup_expired_watch_mode",
    expires=3600,
)
def cleanup_expired_watch_mode(self: BaseTask) -> dict[str, Any]:
    """Часовая уборка режима ожидания (очередь `maintenance`, задача 5.3)."""
    return run_async(_run_watch_cleanup())
