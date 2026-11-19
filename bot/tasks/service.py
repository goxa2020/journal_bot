"""Служебные задачи: smoke-задача `ping` и место для cleanup/collect_metrics (фазы 2–8)."""

from __future__ import annotations

from bot.celery_app import celery_app
from bot.tasks.base import BaseTask


# celery не поставляет типы, поэтому декоратор задачи для mypy нетипизированный.
@celery_app.task(base=BaseTask, bind=True, name="bot.tasks.service.ping")  # type: ignore[untyped-decorator]
def ping(self: BaseTask) -> str:
    """Проверить, что воркер жив и задачи выполняются (очередь `maintenance`).

    Ни БД, ни Telegram, ни Redis: задача для `celery inspect`, ручных проверок и
    smoke-теста в eager-режиме.
    """
    return "pong"
