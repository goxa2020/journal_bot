"""Параметры приложения Celery (docs/ARCHITECTURE.md §6.1–6.2).

Значения берутся из :class:`bot.core.config.CelerySettings` (то есть из `.env`), а не
задаются числами здесь. В этом модуле живут только то, чего нет в настройках: имя
приложения, имена очередей и маршрутизация задач по очередям.
"""

from __future__ import annotations
from typing import Any

from bot.core.config import settings

# Имя приложения: видно в `celery inspect` и в именах узлов (`celery@hostname`).
APP_NAME = "journal_bot"

# Очереди (ARCHITECTURE §6.2). Воркер слушает все три; отдельные воркеры под очередь —
# не в фазе 1.
QUEUE_SYNC = "sync"
QUEUE_NOTIFY = "notify"
QUEUE_MAINTENANCE = "maintenance"

DEFAULT_QUEUE = QUEUE_MAINTENANCE

# Маршрутизация по *именам* задач, а не по объектам: имя известно и тогда, когда задача
# ещё не объявлена в этом процессе. `*` — всё остальное (служебные задачи, cleanup).
TASK_ROUTES: dict[str, dict[str, str]] = {
    "bot.tasks.sync.*": {"queue": QUEUE_SYNC},
    "bot.tasks.notify.*": {"queue": QUEUE_NOTIFY},
    "bot.tasks.maintenance.*": {"queue": QUEUE_MAINTENANCE},
    "*": {"queue": DEFAULT_QUEUE},
}

# Конфигурация приложения Celery. Ключи — имена настроек Celery 5.x.
CELERY_CONFIG: dict[str, Any] = {
    "broker_url": settings.CELERY_BROKER_URL,
    "result_backend": settings.CELERY_RESULT_BACKEND,
    "task_serializer": settings.CELERY_TASK_SERIALIZER,
    "result_serializer": settings.CELERY_RESULT_SERIALIZER,
    "accept_content": list(settings.CELERY_ACCEPT_CONTENT),
    "timezone": settings.CELERY_TIMEZONE,
    "enable_utc": True,
    # Задача подтверждается после выполнения: падение воркера не теряет её, но означает
    # возможный повтор — все задачи обязаны быть идемпотентны (ARCHITECTURE §6.6).
    "task_acks_late": True,
    "task_reject_on_worker_lost": True,
    "worker_prefetch_multiplier": settings.CELERY_WORKER_PREFETCH_MULTIPLIER,
    "task_time_limit": settings.CELERY_TASK_TIME_LIMIT,
    "task_soft_time_limit": settings.CELERY_TASK_SOFT_TIME_LIMIT,
    "worker_max_tasks_per_child": settings.CELERY_WORKER_MAX_TASKS_PER_CHILD,
    "broker_connection_retry_on_startup": True,
    "task_default_queue": DEFAULT_QUEUE,
    "task_queue_max_priority": 10,
    "result_expires": settings.CELERY_RESULT_EXPIRES,
    # Для тестов и локальной отладки; в бою — False (см. .env.example).
    "task_always_eager": settings.CELERY_TASK_ALWAYS_EAGER,
    "task_eager_propagates": settings.CELERY_TASK_ALWAYS_EAGER,
}
