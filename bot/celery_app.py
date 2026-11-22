"""Приложение Celery (docs/ARCHITECTURE.md §6.1).

Точка входа для воркера и beat:

    celery -A bot.celery_app worker -l INFO -Q sync,notify,maintenance
    celery -A bot.celery_app beat -l INFO

Импорт этого модуля не подключается к брокеру: соединение открывается только при
запуске воркера/beat или при постановке задачи (`.delay()`), поэтому приложение можно
импортировать в тестах и в скриптах.
"""

from __future__ import annotations
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_process_shutdown, worker_ready, worker_shutdown

from bot.celery_config import APP_NAME, CELERY_CONFIG, TASK_ROUTES

celery_app = Celery(APP_NAME, include=["bot.tasks.service", "bot.tasks.sync", "bot.tasks.notify"])
celery_app.config_from_object(CELERY_CONFIG, namespace=None)

# Маршрутизация: см. bot/celery_config.py (по именам задач, а не по объектам).
celery_app.conf.task_routes = TASK_ROUTES

# Расписание beat (фаза 4, задача 4.3): плановая синхронизация всех пользователей
# каждые 6 часов — 00, 06, 12, 18 МСК. `expires` не даёт выполнить устаревший дубль из
# очереди, если воркер отставал; сам прогон защищён батч-локом `sync:all:lock`.
# Других записей здесь быть не должно: уведомления ставятся отложенными задачами (`eta`),
# остальные задачи расписания — фазы 5–8.
celery_app.conf.beat_schedule = {
    "sync-all-users": {
        "task": "bot.tasks.sync.sync_all_users",
        "schedule": crontab(minute=0, hour="*/6"),
        "options": {"expires": 3600},
    },
}


# Celery 5.7.0 не поставляет типы, поэтому декоратор сигнала для mypy нетипизированный.
@worker_process_init.connect  # type: ignore[untyped-decorator]
def _configure_task_logging(**_: Any) -> None:
    """Настроить логи задач в каждом процессе воркера (файл + stdout)."""
    from bot.tasks.base import configure_task_logging  # noqa: PLC0415 — воркер уже стартовал

    configure_task_logging()


#: HTTP-сервер метрик главного процесса воркера (W2.1); `None` — режим выключен.
_metrics_server: Any = None


@worker_ready.connect  # type: ignore[untyped-decorator]
def _start_worker_metrics(**_: Any) -> None:
    """Поднять `/metrics` и `/healthz` после старта пула, в главном процессе.

    Именно `worker_ready`, а не `worker_init`: пул уже создан, поэтому HTTP-поток не
    наследуется дочерними процессами. Без `PROMETHEUS_MULTIPROC_DIR` (тесты, локальный
    запуск) сервер не поднимается.
    """
    global _metrics_server  # noqa: PLW0603 — состояние процесса, а не модуля
    from bot.core.worker_metrics import start_worker_metrics_server  # noqa: PLC0415

    _metrics_server = start_worker_metrics_server()


@worker_shutdown.connect  # type: ignore[untyped-decorator]
def _stop_worker_metrics(**_: Any) -> None:
    """Остановить HTTP-сервер метрик вместе с воркером."""
    global _metrics_server  # noqa: PLW0603
    from bot.core.worker_metrics import stop_worker_metrics_server  # noqa: PLC0415

    stop_worker_metrics_server(_metrics_server)
    _metrics_server = None


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def _mark_worker_process_dead(pid: int | None = None, **_: Any) -> None:
    """Убрать mmap-файлы завершившегося дочернего процесса (multiprocess-режим)."""
    from bot.core.worker_metrics import mark_worker_process_dead  # noqa: PLC0415

    mark_worker_process_dead(pid)
