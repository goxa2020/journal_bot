"""Задача 1.7: smoke-проверки приложения Celery.

Всё выполняется в `task_always_eager`, то есть без брокера, Redis и сети: тест
проверяет приложение, маршрутизацию и базовый класс задачи, а не инфраструктуру
(её проверяет `docker compose` и `celery inspect ping`).
"""

from __future__ import annotations

import pytest

from bot.celery_app import celery_app
from bot.tasks.service import ping


def test_ping_eager_returns_pong(celery_eager) -> None:
    assert ping.apply().get() == "pong"


def test_ping_delay_returns_pong_without_broker(celery_eager) -> None:
    """`delay()` в eager-режиме не ходит в Redis — это и есть проверка «без брокера»."""
    assert ping.delay().get(timeout=10) == "pong"


def test_ping_is_routed_to_maintenance() -> None:
    route = celery_app.amqp.router.route({}, "bot.tasks.service.ping")
    assert route["queue"].name == "maintenance"


@pytest.mark.parametrize(
    ("task_name", "queue"),
    [
        ("bot.tasks.sync.sync_user_manual", "sync"),
        ("bot.tasks.sync.sync_user_after_login", "sync"),
        ("bot.tasks.notify.send_grade_notification", "notify"),
        ("bot.tasks.notify.send_night_batch", "notify"),
    ],
)
def test_tasks_are_routed_by_name(task_name: str, queue: str) -> None:
    """Маршрут задаётся именем: задача может быть ещё не объявлена в этом процессе."""
    route = celery_app.amqp.router.route({}, task_name)
    assert route["queue"].name == queue


def test_unknown_task_goes_to_maintenance() -> None:
    route = celery_app.amqp.router.route({}, "bot.tasks.maintenance.cleanup_old_logs")
    assert route["queue"].name == "maintenance"


def test_default_queue_is_maintenance() -> None:
    assert celery_app.conf.task_default_queue == "maintenance"
